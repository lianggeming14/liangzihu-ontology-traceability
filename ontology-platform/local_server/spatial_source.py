"""Verified, lossless private CAD source intake and public candidate derivation."""
from __future__ import annotations

import base64
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import struct
from urllib.parse import quote

from shapely import wkb
from shapely.errors import GEOSException
from shapely.geometry import mapping, shape
from shapely.validation import explain_validity

from .spatial_geometry import build_spatial_map


NAMESPACE = "urn:lzo:cad-gis:v1:"
REGISTRATION_PATH = "data/cad-reference/registration-dataset.json"
REFERENCE_PATH = "data/cad-reference/completion-reference.json"
ANCHORS_PATH = "data/cad-reference/facility-label-positions.json"
CAMERAS_PATH = "定位验证成果/监控摄像头39处.json"
CAMERAS_CSV_PATH = "定位验证成果/监控摄像头39处_坐标表.csv"
PUBLIC_SOURCE_FIELDS = {"code", "name", "kind", "type_label", "drawing", "handle", "village", "source_note",
                        "category", "category_label", "cad_file", "layer_name", "source_class", "confidence",
                        "crs_status", "measure_type", "measure_value", "measure_unit", "source_notice"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _preserve(value):
    if isinstance(value, bytes):
        return {"__type__": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"__type__": "float", "value": "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")}
    if isinstance(value, dict):
        return {str(k): _preserve(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_preserve(v) for v in value]
    return value


def _source_path(root, name):
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise ValueError("invalid source path")
    candidate = (root / name).resolve()
    if Path(name).is_absolute() or not candidate.is_relative_to(root.resolve()):
        raise ValueError("source path escapes input directory")
    return candidate


def _verified_files(inputs_dir, manifest):
    verified = []
    seen = set()
    for entry in sorted(manifest.get("source_files", []), key=lambda item: item["path"]):
        name = entry["path"]
        path = _source_path(inputs_dir, name)
        if name in seen:
            raise ValueError("duplicate source path")
        seen.add(name)
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if len(raw) != entry.get("size_bytes"):
            raise ValueError(f"size mismatch for {name}")
        if blob != entry.get("git_blob_sha"):
            raise ValueError(f"Git blob hash mismatch for {name}")
        sha256 = hashlib.sha256(raw).hexdigest()
        if entry.get("sha256") and sha256 != entry["sha256"]:
            raise ValueError(f"SHA256 mismatch for {name}")
        file_id = _digest([manifest.get("repository"), entry.get("commit"), name, sha256])
        verified.append(({**entry, "id": file_id, "file_id": file_id, "sha256": sha256,
                          "original_path": "source-files/" + name}, path, raw))
    return verified


def _record(file_id, table, index, payload):
    return {"id": NAMESPACE + "source:" + _digest([file_id, table, index]), "file_id": file_id,
            "table": table, "row_number": index, "payload": _preserve(payload), "status": "accepted", "issues": []}


def _table(file_id, name, columns, records, **extra):
    quarantined = sum(r["status"] == "quarantined" for r in records)
    return {"file_id": file_id, "name": name, "columns": columns, "row_count": len(records),
            "received_count": len(records), "quarantined_count": quarantined, **extra}


def _parse_gpkg_geometry(raw):
    if len(raw) < 8 or raw[:2] != b"GP" or raw[2] != 0:
        raise ValueError("invalid_geopackage_geometry_header")
    flags = raw[3]
    envelope_type = (flags >> 1) & 7
    if envelope_type > 4 or flags & 0b11000000:
        raise ValueError("unsupported_geopackage_geometry_flags")
    if flags & 0b00100000:
        raise ValueError("extended_geopackage_geometry_not_supported")
    byte_order = "<" if flags & 1 else ">"
    srid = struct.unpack(byte_order + "i", raw[4:8])[0]
    offset = 8 + [0, 4, 6, 6, 8][envelope_type] * 8
    if len(raw) <= offset:
        raise ValueError("truncated_geopackage_geometry")
    geometry = wkb.loads(raw[offset:])
    return json.loads(json.dumps(mapping(geometry))), srid, geometry


def _read_gpkg(file, path):
    records, tables = [], []
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as db:
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        geometry_columns = {}
        unknown_srids = {-1, 0}
        if "gpkg_spatial_ref_sys" in names:
            for srid, definition in db.execute("SELECT srs_id,definition FROM gpkg_spatial_ref_sys"):
                if not definition or any(word in definition.lower() for word in ("undefined", "unknown", "local_cs")):
                    unknown_srids.add(srid)
        if "gpkg_geometry_columns" in names:
            for row in db.execute("SELECT table_name,column_name,srs_id FROM gpkg_geometry_columns"):
                geometry_columns.setdefault(row[0], []).append((row[1], row[2]))
        for name in names:
            identifier = '"' + name.replace('"', '""') + '"'
            schema = list(db.execute(f"PRAGMA table_info({identifier})"))
            columns = [row[1] for row in schema]
            try:
                rows = db.execute(f"SELECT * FROM {identifier} ORDER BY rowid")
            except sqlite3.OperationalError:
                # WITHOUT ROWID tables use their declared primary-key order.
                primary = [row[1] for row in sorted(schema, key=lambda r: r[5]) if row[5]]
                ordering = ",".join('"' + col.replace('"', '""') + '"' for col in primary)
                rows = db.execute(f"SELECT * FROM {identifier}" + (" ORDER BY " + ordering if ordering else ""))
            table_records = []
            for index, row in enumerate(rows, 1):
                payload = dict(zip(columns, row))
                record = _record(file["id"], name, index, payload)
                if name in geometry_columns and name.startswith("隔离_"):
                    record["issues"].append("source_quarantine_table")
                geometries = []
                for column, declared_srid in geometry_columns.get(name, []):
                    raw = payload.get(column)
                    if raw is None:
                        record["issues"].append("missing_geometry")
                        continue
                    try:
                        geometry, srid, parsed = _parse_gpkg_geometry(raw)
                        item = {"column": column, "geometry": geometry, "source_srid": srid, "declared_srid": declared_srid}
                        try:
                            json.dumps(geometry, allow_nan=False)
                        except ValueError:
                            # Keep an explicit lossless decoded representation outside
                            # the GeoJSON slot; nonfinite coordinates are not geometry.
                            decoded = _preserve(geometry)
                            item.update({"geometry": None, "decoded_geometry": decoded})
                            record.setdefault("decoded_geometry", decoded)
                            record["issues"].append("nonfinite_geometry_coordinate")
                        geometries.append(item)
                        record.setdefault("geometry", item["geometry"])
                        record.setdefault("source_srid", srid)
                        if srid != declared_srid:
                            record["issues"].append("geometry_srid_mismatch")
                        if srid in unknown_srids or str(payload.get("crs_status", "")).upper() == "UNKNOWN":
                            record["issues"].append("unknown_crs")
                        if parsed.is_empty or not parsed.is_valid:
                            record["issues"].append("invalid_geometry: " + explain_validity(parsed))
                    except Exception as exc:
                        record["issues"].append("geometry_parse_error: " + str(exc))
                if geometries:
                    record["geometries"] = geometries
                if record["issues"]:
                    record["status"] = "quarantined"
                table_records.append(record)
            records.extend(table_records)
            tables.append(_table(file["id"], name, columns, table_records,
                                 column_definitions=[{"name": r[1], "type": r[2], "not_null": bool(r[3]), "default": r[4], "primary_key_order": r[5]} for r in schema]))
    return tables, records


def _read_json(file, raw):
    document = json.loads(raw.decode("utf-8-sig"))

    def json_record(table, number, payload):
        record = _record(file["id"], table, number, payload)
        geometry = payload.get("geometry") if isinstance(payload, dict) else None
        if geometry is not None:
            try:
                parsed = shape(geometry)
                if parsed.is_empty or not parsed.is_valid:
                    raise ValueError(explain_validity(parsed))
            except (ValueError, TypeError, KeyError, GEOSException) as exc:
                record["status"] = "quarantined"
                record["issues"].append("invalid_geometry: " + str(exc))
        return record

    root_record = json_record("$document", 1, document)
    tables = [_table(file["id"], "$document", list(document) if isinstance(document, dict) else ["value"], [root_record])]
    records = [root_record]

    def walk(value, pointer):
        if isinstance(value, list):
            rows = [json_record(pointer or "$items", i, row) for i, row in enumerate(value, 1)]
            columns = list(dict.fromkeys(k for row in value if isinstance(row, dict) for k in row))
            tables.append(_table(file["id"], pointer or "$items", columns or ["value"], rows))
            records.extend(rows)
        elif isinstance(value, dict):
            for key, child in value.items():
                walk(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
    walk(document, "")
    return tables, records, document


def _read_csv(file, raw):
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    columns = next(reader, [])
    records = []
    for index, values in enumerate(reader, 1):
        if len(columns) == len(set(columns)) and len(values) == len(columns):
            payload = dict(zip(columns, values))
        else:
            payload = {"__columns__": columns, "__values__": values}
        record = _record(file["id"], "csv", index, payload)
        if {"原始X", "原始Y"}.issubset(payload):
            crs_status = str(payload.get("坐标参考", "")).strip()
            if not crs_status or crs_status.upper() == "UNKNOWN" or any(word in crs_status for word in ("未确认", "未知", "未核实")):
                record["issues"].append("unknown_crs")
            height_status = str(payload.get("Z审核状态", "")) + " " + str(payload.get("垂直高程基准", ""))
            if any(word in height_status for word in ("未确认", "未知", "未核实", "候选")):
                record["issues"].append("unverified_vertical_datum")
        if record["issues"]:
            record["status"] = "quarantined"
        records.append(record)
    return [_table(file["id"], "csv", columns, records)], records


def _derive_candidates(documents, files, records):
    """Derive only the reviewed transformed sources; raw GPKGs are never guessed."""
    by_path = {file["path"]: file for file in files}
    record_lookup = {(r["file_id"], r["table"], r["row_number"]): r for r in records}
    objects, relations = [], []
    by_code, by_cad_key, by_drawing = {}, {}, {}
    quality = {"duplicate_source_references": 0, "unmatched_reference_land": [], "reference_geometry_mismatches": [],
               "unmatched_facility_anchors": [], "duplicate_cad_codes": [], "ambiguous_spatial_hits": [], "camera_csv_mismatches": []}

    def source(path, table, number):
        file = by_path[path]
        record = record_lookup[(file["id"], table, number)]
        ref = {key: file[key] for key in ("file_id", "path", "commit", "git_blob_sha", "sha256", "url") if key in file}
        ref.update({"table": table, "row_number": number})
        return ref, record["id"]

    def candidate(identifier, label, kind, geometry, path, table, number, payload, status=None):
        ref, record_id = source(path, table, number)
        result = {"id": identifier, "iri": NAMESPACE + "instance:" + quote(identifier, safe="-._~"),
                  "class_key": kind, "class_iri": NAMESPACE + "class:" + kind,
                  "label": label, "kind": kind, "geometry": copy.deepcopy(geometry), "source_refs": [ref],
                  "source_record_ids": [record_id], "attributes": {"source_values": [{key: value for key, value in payload.items() if key in PUBLIC_SOURCE_FIELDS}],
                  "original_cad_crs_status": "UNKNOWN", "registration_status": "candidate_approximate", "depth_m": None,
                  "area_memberships": []},
                  "position_status": status or ("candidate_approximate" if geometry else "unlocated"),
                  "nature": "cad_candidate_unverified", "layer_id": kind}
        objects.append(result)
        return result

    def append_evidence(obj, path, table, number, payload):
        ref, record_id = source(path, table, number)
        obj["source_refs"].append(ref)
        obj["source_record_ids"].append(record_id)
        obj["attributes"]["source_values"].append({key: value for key, value in payload.items() if key in PUBLIC_SOURCE_FIELDS})

    def diagram_relation(obj, drawing):
        region = by_drawing.get(drawing)
        if region:
            relations.append({"subject": obj["iri"], "predicate": NAMESPACE + "property:sourceDiagramRegion", "object": region["iri"],
                              "evidence": {"basis": "exact source drawing identity", "drawing": drawing,
                                           "source_refs": obj["source_refs"][:1] + region["source_refs"]}, "status": "source_declared_diagram_group"})

    registration = documents.get(REGISTRATION_PATH, {})
    for number, row in enumerate(registration.get("villages", []), 1):
        # A source grouping is not a surveyed administrative polygon.
        region = candidate("region-" + str(row["code"]), row.get("name", row["code"]), "region", None,
                           REGISTRATION_PATH, "/villages", number, row, "source_diagram_group")
        by_drawing[row["drawing"]] = region
    for number, row in enumerate(registration.get("items", []), 1):
        code = str(row["code"])
        if code in by_code:
            quality["duplicate_cad_codes"].append({"code": code, "source_ref": source(REGISTRATION_PATH, "/items", number)[0]})
            append_evidence(by_code[code], REGISTRATION_PATH, "/items", number, row)
            continue
        obj = candidate(code, row.get("name", code), row["kind"], row.get("geometry"), REGISTRATION_PATH, "/items", number, row)
        by_code[code] = obj
        by_cad_key[Path(row["drawing"]).stem + "__" + str(row["handle"])] = obj
        diagram_relation(obj, row["drawing"])

    reference = documents.get(REFERENCE_PATH, {})
    for number, row in enumerate(reference.get("features", []), 1):
        properties = row.get("properties", {})
        kind = properties.get("category")
        if kind == "land":
            obj = by_cad_key.get(row.get("id"))
            if obj is None:
                quality["unmatched_reference_land"].append(source(REFERENCE_PATH, "/features", number)[0])
                continue
            append_evidence(obj, REFERENCE_PATH, "/features", number, properties)
            if obj["geometry"] == row.get("geometry"):
                quality["duplicate_source_references"] += 1
            else:
                quality["reference_geometry_mismatches"].append({"iri": obj["iri"], "source_ref": source(REFERENCE_PATH, "/features", number)[0]})
        elif kind in {"road", "canal"}:
            identifier = kind + "-" + _digest([row.get("id"), properties.get("cad_file"), properties.get("handle")])
            obj = candidate(identifier, properties.get("category_label", kind) + " " + str(properties.get("handle", number)),
                            kind, row.get("geometry"), REFERENCE_PATH, "/features", number, properties)
            diagram_relation(obj, properties.get("cad_file"))

    anchors = documents.get(ANCHORS_PATH, {})
    for number, row in enumerate(anchors.get("positions", []), 1):
        obj = by_code.get(row.get("code"))
        if obj is None or obj["kind"] != "facility":
            quality["unmatched_facility_anchors"].append(source(ANCHORS_PATH, "/positions", number)[0])
            continue
        append_evidence(obj, ANCHORS_PATH, "/positions", number, row)
        obj["geometry"] = copy.deepcopy(row.get("geometry"))
        obj["position_status"] = "candidate_text_anchor" if obj["geometry"] else "unlocated"
        obj["attributes"]["position_basis"] = "CAD annotation text anchor; not facility insertion position"

    camera_csv = {}
    if CAMERAS_CSV_PATH in by_path:
        csv_id = by_path[CAMERAS_CSV_PATH]["id"]
        camera_csv = {r["row_number"]: r for r in records if r["file_id"] == csv_id and r["table"] == "csv"}
    for number, row in enumerate(documents.get(CAMERAS_PATH, []), 1):
        identifier = "camera-" + _digest([by_path[CAMERAS_PATH]["id"], number, row])
        longitude, latitude = row.get("经度"), row.get("纬度")
        geometry = {"type": "Point", "coordinates": [longitude, latitude]} if longitude is not None and latitude is not None else None
        obj = candidate(identifier, f"摄像头候选 {number:02d}", "camera", geometry, CAMERAS_PATH, "$items", number, {},
                        "candidate_cad_symbol" if geometry else "unlocated")
        obj["attributes"].update({"device_iri": None, "position_basis": "CAD camera symbol; no installed device identity",
                                   "source_candidate_number": number})
        csv_row = camera_csv.get(number)
        if csv_row:
            payload = csv_row["payload"]
            try:
                matches = float(payload["经度CGCS2000"]) == longitude and float(payload["纬度CGCS2000"]) == latitude
            except (ValueError, TypeError, KeyError):
                matches = False
            if matches:
                append_evidence(obj, CAMERAS_CSV_PATH, "csv", number, {})
            else:
                quality["camera_csv_mismatches"].append({"iri": obj["iri"], "row_number": number})

    areas = []
    for obj in objects:
        geometry = obj.get("geometry")
        if geometry and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            try:
                polygon = shape(geometry)
                if polygon.is_valid and not polygon.is_empty:
                    areas.append((obj, polygon))
            except (ValueError, TypeError, KeyError, GEOSException):
                pass  # The map quality catalog records the unchanged invalid geometry.
    for obj in objects:
        geometry = obj.get("geometry")
        if not geometry or geometry.get("type") != "Point":
            continue
        try:
            point = shape(geometry)
            hits = [area for area, polygon in areas if polygon.covers(point)] if point.is_valid and not point.is_empty else []
        except (ValueError, TypeError, KeyError, GEOSException):
            continue
        if len(hits) > 1:
            quality["ambiguous_spatial_hits"].append({"iri": obj["iri"], "area_iris": [area["iri"] for area in hits]})
        for area in hits:
            evidence = {"algorithm": "shapely.covers", "display_srid": 4326, "boundary_policy": "boundary included",
                        "registration_status": "candidate_approximate", "business_ownership": False,
                        "hit_count": len(hits), "ambiguous": len(hits) > 1,
                        "source_refs": obj["source_refs"] + area["source_refs"]}
            status = "derived_candidate_spatial_evidence"
            relations.append({"subject": obj["iri"], "predicate": NAMESPACE + "property:spatiallyWithinCandidate", "object": area["iri"],
                              "evidence": evidence, "status": status})
            obj["attributes"]["area_memberships"].append({"area_iri": area["iri"], "evidence": copy.deepcopy(evidence), "status": status})
    quality["candidate_counts"] = {"registered_cad_objects": len(by_code),
        **{kind: sum(obj["kind"] == kind for obj in objects) for kind in ("field", "pond", "facility", "camera", "road", "canal", "region")},
        "facility_text_anchors": sum(obj["position_status"] == "candidate_text_anchor" for obj in objects),
        "unlocated_facilities": sum(obj["kind"] == "facility" and not obj["geometry"] for obj in objects)}
    return objects, relations, quality


def _source_expectations(source_manifest, candidate_counts):
    comparisons = [
        ("registration", "objects", "registered_cad_objects"),
        ("registration", "fields", "field"), ("registration", "ponds", "pond"),
        ("registration", "facilities", "facility"), ("registration", "polygon_geometries", "positioned_polygons"),
        ("facility_label_anchors", "positions", "positioned_facility_text_anchors"),
        ("facility_label_anchors", "unpositioned", "unlocated_facilities"),
        ("cameras", "cad_symbols", "positioned_cameras"),
        ("reference", "land", "duplicate_source_references"),
        ("reference", "road", "road"), ("reference", "canal", "canal"),
    ]
    results = {}
    for section, field, key in comparisons:
        expected = source_manifest.get(section, {}).get(field)
        if isinstance(expected, int):
            actual = candidate_counts[key]
            results[key] = {"expected": expected, "actual": actual, "delta": actual - expected,
                            "status": "passed" if actual == expected else "mismatch"}
    return results


def prepare_cad_bundle(inputs_dir: Path, output_dir: Path, source_manifest: dict) -> dict:
    """Verify every pinned input before writing a deterministic private bundle.

    ``bundle.json`` contains complete source payloads and must stay private.
    Only its separately written ``map.json`` is a public display artifact.
    """
    inputs_dir, output_dir = Path(inputs_dir), Path(output_dir)
    verified = _verified_files(inputs_dir, source_manifest)
    files = [entry for entry, _, _ in verified]
    batch_id = _digest([{key: row.get(key) for key in ("path", "commit", "git_blob_sha", "sha256")} for row in files])
    existing_bundle = output_dir / "bundle.json"
    previous = None
    if existing_bundle.exists():
        previous = json.loads(existing_bundle.read_text(encoding="utf-8"))
        if previous.get("batch_id") != batch_id:
            raise ValueError("output directory already contains a different batch")
        if _digest(previous.get("source_files")) != _digest(files):
            raise ValueError("immutable batch source identity or metadata changed")
    tables, records, documents = [], [], {}
    for file, path, raw in verified:
        suffix = path.suffix.lower()
        if suffix == ".gpkg":
            new_tables, new_records = _read_gpkg(file, path)
        elif suffix == ".json":
            new_tables, new_records, document = _read_json(file, raw)
            documents[file["path"]] = document
        elif suffix == ".csv":
            new_tables, new_records = _read_csv(file, raw)
        else:
            new_records = [_record(file["id"], "text", 1, {"text": raw.decode("utf-8-sig")})]
            new_tables = [_table(file["id"], "text", ["text"], new_records)]
        tables.extend(new_tables)
        records.extend(new_records)
    objects, relations, quality = _derive_candidates(documents, files, records)
    spatial_map = build_spatial_map(objects)
    public_by_iri = {obj["iri"]: obj for obj in spatial_map["features"] + spatial_map["unlocated"]}
    records_by_id = {row["id"]: row for row in records}
    for obj in objects:
        display = public_by_iri[obj["iri"]]
        if "computed_measurements" in display["attributes"]:
            obj["attributes"]["computed_measurements"] = display["attributes"]["computed_measurements"]
        obj["attributes"]["exclude_from_initial_fit"] = display["attributes"].get("exclude_from_initial_fit", False)
        if display["position_status"] == "invalid_geometry_quarantined":
            obj["position_status"] = display["position_status"]
            for record_id in obj["source_record_ids"]:
                record = records_by_id[record_id]
                record["status"] = "quarantined"
                if "invalid_display_geometry" not in record["issues"]:
                    record["issues"].append("invalid_display_geometry")
    quarantined_by_table = {}
    for record in records:
        if record["status"] == "quarantined":
            key = (record["file_id"], record["table"])
            quarantined_by_table[key] = quarantined_by_table.get(key, 0) + 1
    for table in tables:
        table["quarantined_count"] = quarantined_by_table.get((table["file_id"], table["name"]), 0)
    quality["candidate_counts"].update({
        "positioned_polygons": sum(o["kind"] in {"field", "pond"} and o["geometry"]["type"] in {"Polygon", "MultiPolygon"} for o in spatial_map["features"]),
        "positioned_facility_text_anchors": sum(o["position_status"] == "candidate_text_anchor" for o in spatial_map["features"]),
        "positioned_cameras": sum(o["kind"] == "camera" for o in spatial_map["features"]),
        "unlocated_facilities": sum(o["kind"] == "facility" for o in spatial_map["unlocated"]),
        "duplicate_source_references": quality["duplicate_source_references"],
    })
    quality["source_expectations"] = _source_expectations(source_manifest, quality["candidate_counts"])
    spatial_map["quality"]["source_expectations"] = quality["source_expectations"]
    spatial_map["quality"]["candidate_counts"] = quality["candidate_counts"]
    quality.update({"quarantined_source_records": sum(r["status"] == "quarantined" for r in records),
                    "source_rows_lost": 0, "map": spatial_map["quality"]})
    counts = {"source_files": len(files), "source_tables": len(tables), "source_records": len(records),
              "objects": len(objects), "relations": len(relations), "positioned": len(spatial_map["features"]),
              "unlocated": len(spatial_map["unlocated"]), "quarantined_source_records": quality["quarantined_source_records"],
              **quality["candidate_counts"]}
    bundle = {"contract": "lzo-cad-batch/1", "batch_id": batch_id, "namespace": NAMESPACE,
              "source_files": files, "source_tables": tables, "source_records": records,
              "objects": objects, "relations": relations, "map": spatial_map, "quality": quality, "counts": counts}
    if previous is not None and _digest(previous) != _digest(bundle):
        raise ValueError("immutable batch content or metadata changed")
    output_dir.mkdir(parents=True, exist_ok=True)
    for file, _, raw in verified:
        destination = _source_path(output_dir, file["original_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    for name, payload in (("bundle.json", bundle), ("map.json", spatial_map)):
        temporary = output_dir / (name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output_dir / name)
    return bundle
