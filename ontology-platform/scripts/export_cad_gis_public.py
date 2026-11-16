"""Reproducible whitelist export of reviewed candidate GIS data; no service writes."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
from rdflib.plugins.serializers.nt import _quoteLiteral


NS = "urn:lzo:cad-gis:v1:"
KINDS = {"field", "pond", "facility", "camera", "road", "canal", "region"}
RELATION_NAMES = {"sourceDiagramRegion", "spatiallyWithinCandidate"}
SOURCE_VALUE_KEYS = {"code", "name", "kind", "type_label", "drawing", "handle", "village", "source_note",
                     "category", "category_label", "cad_file", "layer_name", "source_class", "confidence",
                     "crs_status", "measure_type", "measure_value", "measure_unit", "source_notice"}
COUNT_KEYS = KINDS | {"registered_cad_objects", "facility_text_anchors", "unlocated_facilities", "positioned_polygons",
                     "positioned_facility_text_anchors", "positioned_cameras", "duplicate_source_references"}


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _scalars(row, keys):
    result = {}
    for key in sorted(keys):
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, (str, int, float, bool, type(None))) or isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-scalar or nonfinite public value: " + key)
        result[key] = value
    return result


def _instance(value):
    if not isinstance(value, str) or not re.fullmatch(re.escape(NS) + r"instance:[A-Za-z0-9._~%:-]+", value):
        raise ValueError("Invalid public candidate identity")
    return value


def _geometry(value):
    if value is None:
        return None
    if value.get("type") not in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
        raise ValueError("Unsupported public geometry")

    def coordinates(item):
        if isinstance(item, list):
            return [coordinates(child) for child in item]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ValueError("Invalid public geometry coordinate")
        return item

    return {"type": value["type"], "coordinates": coordinates(value["coordinates"])}


def _public_documents(bundle):
    if bundle.get("contract") != "lzo-cad-batch/1" or bundle.get("namespace") != NS:
        raise ValueError("Unsupported private bundle contract")
    if not re.fullmatch(r"[0-9a-f]{64}", bundle.get("batch_id", "")):
        raise ValueError("Invalid source batch identity")
    files = []
    for row in bundle["source_files"]:
        file = _scalars(row, {"file_id", "path", "commit", "git_blob_sha", "sha256", "size_bytes", "url"})
        path = file["path"]
        if not isinstance(path, str) or ":" in path or "\\" in path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or ".runtime" in PurePosixPath(path).parts:
            raise ValueError("Source path is not a public repository path")
        if file.get("url"):
            url = urlsplit(file["url"])
            if url.scheme != "https" or url.hostname != "github.com" or url.username or url.password or url.query or url.fragment:
                raise ValueError("Source URL is not a public GitHub evidence URL")
        files.append(file)
    files.sort(key=lambda row: row["path"])
    file_by_id = {row["file_id"]: row for row in files}
    if len(file_by_id) != len(files):
        raise ValueError("Duplicate public source-file identity")
    tables = []
    for row in bundle["source_tables"]:
        table = _scalars(row, {"file_id", "name", "row_count", "received_count", "quarantined_count"})
        if table["file_id"] not in file_by_id or not all(isinstance(col, str) for col in row["columns"]):
            raise ValueError("Invalid public source-table inventory")
        table["columns"] = list(row["columns"])
        tables.append(table)
    tables.sort(key=lambda row: (row["file_id"], row["name"]))
    table_by_key = {(row["file_id"], row["name"]): row for row in tables}

    def refs(rows):
        results = []
        for row in rows:
            file = file_by_id.get(row.get("file_id"))
            table = table_by_key.get((row.get("file_id"), row.get("table")))
            number = row.get("row_number")
            if file is None or table is None or type(number) is not int or not 1 <= number <= table["row_count"]:
                raise ValueError("Unresolved public source reference")
            results.append({**file, "table": row["table"], "row_number": number})
        return results

    object_iris = {_instance(row["iri"]) for row in bundle["objects"]}
    if len(object_iris) != len(bundle["objects"]):
        raise ValueError("Duplicate candidate identity")

    def endpoint(iri):
        if _instance(iri) not in object_iris:
            raise ValueError("Unresolved candidate endpoint")
        return iri

    def evidence(row):
        result = _scalars(row, {"basis", "drawing", "algorithm", "display_srid", "boundary_policy", "registration_status", "business_ownership", "hit_count", "ambiguous"})
        if "source_refs" in row:
            result["source_refs"] = refs(row["source_refs"])
        return result

    def status(row):
        value = _scalars(row, {"status"}).get("status")
        if not isinstance(value, str):
            raise ValueError("Invalid public relation status")
        return value

    def feature(row):
        value = _scalars(row, {"id", "iri", "class_iri", "class_key", "label", "kind", "layer_id", "nature", "position_status"})
        endpoint(value["iri"])
        if value["kind"] not in KINDS or value["class_iri"] != NS + "class:" + value["kind"]:
            raise ValueError("Invalid candidate class")
        value["geometry"] = _geometry(row.get("geometry"))
        value["source_refs"] = refs(row.get("source_refs", []))
        attrs = row.get("attributes", {})
        public = _scalars(attrs, {"depth_m", "device_iri", "position_basis", "source_candidate_number", "exclude_from_initial_fit", "original_cad_crs_status", "registration_status"})
        if public.get("device_iri") is not None:
            raise ValueError("This candidate export does not authorize a real-device binding")
        if "computed_measurements" in attrs:
            measured = attrs["computed_measurements"]
            public["computed_measurements"] = _scalars(measured, {"area_m2", "perimeter_m", "length_m", "method", "assumptions"})
            public["computed_measurements"]["units"] = _scalars(measured.get("units", {}), {"area", "perimeter", "length"})
        public["source_values"] = [_scalars(source, SOURCE_VALUE_KEYS) for source in attrs.get("source_values", [])]
        public["area_memberships"] = [{"area_iri": endpoint(member["area_iri"]), "status": status(member), "evidence": evidence(member.get("evidence", {}))} for member in attrs.get("area_memberships", [])]
        value["attributes"] = public
        return value

    objects = sorted((feature(row) for row in bundle["objects"]), key=lambda row: row["iri"])
    relations = []
    for row in bundle["relations"]:
        if row["predicate"] not in {NS + "property:" + key for key in RELATION_NAMES}:
            raise ValueError("Unsupported candidate relation predicate")
        relations.append({"subject": endpoint(row["subject"]), "predicate": row["predicate"], "object": endpoint(row["object"]),
                          "status": status(row), "evidence": evidence(row.get("evidence", {}))})
    relations.sort(key=lambda row: (row["subject"], row["predicate"], row["object"]))
    source_map = bundle["map"]
    if source_map.get("contract") != "lzo-spatial-map/2":
        raise ValueError("Unsupported map contract")
    bounds = source_map.get("bounds")
    if bounds is not None and (not isinstance(bounds, list) or len(bounds) != 4 or any(type(value) not in {int, float} or not math.isfinite(value) for value in bounds)):
        raise ValueError("Invalid public map bounds")
    display = []
    for row in source_map["display_features"]:
        face = _scalars(row, {"id", "kind", "layer_id", "conflict"})
        face["geometry"] = _geometry(row["geometry"])
        face["object_iris"] = [endpoint(iri) for iri in row["object_iris"]]
        display.append(face)
    quality_source = source_map.get("quality", {})
    quality = _scalars(quality_source, {"area_tolerance_m2", "boundaries_simplified", "boundaries_snapped", "partition_crs", "partition_method"})
    quality["candidate_counts"] = _scalars(quality_source.get("candidate_counts", {}), COUNT_KEYS)
    quality["source_expectations"] = {key: _scalars(value, {"expected", "actual", "delta", "status"}) for key, value in quality_source.get("source_expectations", {}).items() if key in COUNT_KEYS}
    quality["conflict_faces"] = [{**_scalars(row, {"id", "area_m2", "above_numerical_tolerance"}), "object_iris": [endpoint(iri) for iri in row["object_iris"]]} for row in quality_source.get("conflict_faces", [])]
    quality["invalid_geometry"] = [_scalars(row, {"iri", "reason", "action"}) for row in quality_source.get("invalid_geometry", [])]
    quality["anomalous_lengths"] = [_scalars(row, {"iri", "length_m", "threshold_m", "action"}) for row in quality_source.get("anomalous_lengths", [])]
    quality["initial_fit_exclusions"] = [endpoint(iri) for iri in quality_source.get("initial_fit_exclusions", [])]
    spatial_map = {"contract": "lzo-spatial-map/2", "crs": _scalars(source_map["crs"], {"display_srid", "registration_status", "original_cad_crs_status", "display_z"}),
                   "features": [feature(row) for row in source_map["features"]], "unlocated": [feature(row) for row in source_map["unlocated"]],
                   "display_features": display, "bounds": bounds,
                   "layers": [_scalars(row, {"id", "label", "visible"}) for row in source_map["layers"]], "quality": quality}
    if {row["iri"] for row in spatial_map["features"] + spatial_map["unlocated"]} != object_iris:
        raise ValueError("Map and public object identities disagree")
    counts = {"source_files": len(files), "source_tables": len(tables), "source_records_retained_privately": sum(row["row_count"] for row in tables),
              "quarantined_source_records_retained_privately": sum(row["quarantined_count"] for row in tables),
              "objects": len(objects), "relations": len(relations), "positioned": len(spatial_map["features"]), "unlocated": len(spatial_map["unlocated"]),
              "objects_by_kind": dict(sorted(Counter(row["kind"] for row in objects).items())),
              "canonical_polygon_count": sum(row["geometry"] is not None and row["geometry"]["type"] in {"Polygon", "MultiPolygon"} for row in objects),
              "canonical_polygons_by_kind": dict(sorted(Counter(row["kind"] for row in objects if row["geometry"] is not None and row["geometry"]["type"] in {"Polygon", "MultiPolygon"}).items())),
              "canonical_field_pond_polygons": sum(row["kind"] in {"field", "pond"} and row["geometry"] is not None and row["geometry"]["type"] in {"Polygon", "MultiPolygon"} for row in objects),
              "display_faces": len(display), "display_faces_by_kind": dict(sorted(Counter(row["kind"] for row in display).items())),
              "conflict_faces": sum(bool(row["conflict"]) for row in display)}
    common = {"source_batch_id": bundle["batch_id"], "namespace": NS}
    documents = {"map.json": spatial_map,
                 "objects.json": {"contract": "lzo-cad-public-objects/1", **common, "objects": objects},
                 "relations.json": {"contract": "lzo-cad-public-relations/1", **common, "relations": relations},
                 "provenance.json": {"contract": "lzo-cad-public-provenance/1", **common, "raw_records_included": False, "counts": counts,
                                     "source_files": files, "source_tables": tables}}
    return documents, counts


def _business_rdf(objects, relations):
    """Project only sanitized candidates; never call private-source RDF iteration."""
    graph = Graph()
    vocab = Namespace(NS + "property:")
    for kind in sorted({obj["kind"] for obj in objects}):
        graph.add((URIRef(NS + "class:" + kind), RDF.type, OWL.Class))

    def literal(value):
        return Literal(_json_bytes(value).decode().strip(), datatype=RDF.JSON)

    for obj in objects:
        iri = URIRef(obj["iri"])
        graph.add((iri, RDF.type, URIRef(obj["class_iri"])))
        graph.add((iri, RDFS.label, Literal(obj["label"])))
        graph.add((iri, vocab.dataNature, Literal(obj["nature"])))
        graph.add((iri, vocab.positionStatus, Literal(obj["position_status"])))
        graph.add((iri, vocab.sourceEvidence, literal(obj["source_refs"])))
        graph.add((iri, vocab.attributes, literal(obj["attributes"])))
        if obj["geometry"] is not None:
            graph.add((iri, vocab.geometryEvidence, literal({"display_srid": 4326, "registration_status": "candidate_approximate", "original_cad_crs_status": "UNKNOWN", "geometry": obj["geometry"]})))
        for key in ("area_m2", "perimeter_m", "length_m"):
            value = obj["attributes"].get("computed_measurements", {}).get(key)
            if value is not None:
                graph.add((iri, vocab[key], Literal(str(value), datatype=XSD.decimal)))
    for row in relations:
        subject, predicate, target = map(URIRef, (row["subject"], row["predicate"], row["object"]))
        graph.add((subject, predicate, target))
        graph.add((predicate, RDF.type, OWL.ObjectProperty))
        statement = URIRef(NS + "statement:" + hashlib.sha256(_json_bytes(row)).hexdigest())
        for prop, value in ((RDF.type, RDF.Statement), (RDF.subject, subject), (RDF.predicate, predicate), (RDF.object, target), (vocab.relationEvidence, literal(row))):
            graph.add((statement, prop, value))
    lines = []
    for subject, predicate, obj in sorted(graph, key=lambda row: tuple(term.n3() for term in row)):
        lines.append(subject.n3() + " " + predicate.n3() + " " + (_quoteLiteral(obj) if isinstance(obj, Literal) else obj.n3()) + " .\n")
    return "".join(lines).encode("utf-8"), len(graph)


def _readme(counts, batch_id):
    kinds = counts["objects_by_kind"]
    return f"""# CAD/GIS 公开派生数据

固定来源批次：`{batch_id}`。本目录由 `scripts/export_cad_gis_public.py` 使用显式字段白名单导出；没有复制源文件原件、完整 SourceRecord、原始 GPKG/CSV 数据、私有记录 IRI、数据库或运行目录。

- `map.json`：`lzo-spatial-map/2` 平面地图；面只从 `display_features` 绘制，点/线从 `features` 绘制。
- `objects.json`：{counts['objects']} 个候选对象、计算测量、来源文件/行引用；未知深度保持 null。
- `relations.json`：{counts['relations']} 条图纸分组和带算法证据的空间关系，不能解释为业务所有权。
- `provenance.json`：{counts['source_files']} 个来源文件的固定提交/摘要及 {counts['source_tables']} 张来源表的列名与数量；完整 {counts['source_records_retained_privately']} 条来源记录保留在私有批次。
- `business.nt`：仅上述公开候选对象/关系的 RDF 投影，可用 RDFLib 按 N-Triples 读取，不等同于全库 RDF 或完整私有来源图。
- `manifest.json`：输出 SHA256、大小、计数与来源批次摘要；没有时间戳或本机路径，重复导出字节稳定。

来源表计数包含 GPKG 元数据/RTree 表，以及 JSON 整份文档和清单记录；来源记录数不是独立实物或资产数量。同一实物候选的多个来源表示仍分别保留于私有批次。

坐标是来源已转换的候选经纬度：display_srid=4326，registration_status=candidate_approximate，original_cad_crs_status=UNKNOWN。显示为平面；没有把未知原始坐标猜测投影，也没有独立确认 CAD 原始 CRS 或现场精度。WGS84 椭球测量是派生计算值，算法/单位/假设与源值分开保存；未知塘深没有用高程代替。

摄像头共 {kinds.get('camera', 0)} 个 CAD 摄像头符号候选，不是 {kinds.get('camera', 0)} 台已核实真实设备：没有绑定 device_iri、序列号、在线状态或视频入口。设施点来自文字标注锚点，不能称为设施实物插入点；无位置对象仍为 null，不补造坐标。图纸分组不是新增行政区域边界。

源面与显示面口径：{counts['canonical_field_pond_polygons']} 个田塘规范面；全部规范多边形 {counts['canonical_polygon_count']} 个（其中道路面 {counts['canonical_polygons_by_kind'].get('road', 0)} 个、沟渠面 {counts['canonical_polygons_by_kind'].get('canal', 0)} 个）。显示分片 {counts['display_faces']} 个，按 kind 为 `{json.dumps(counts['display_faces_by_kind'], ensure_ascii=False, sort_keys=True)}`。真实正面积交叠保留全部 object_iris，面片只画一次；道路/沟渠默认隐藏。显示去重不删除来源引用。

复现（在 ontology-platform 目录执行；PRIVATE_BUNDLE_JSON 指向已核验的私有 bundle.json）：

```powershell
python scripts/export_cad_gis_public.py --bundle PRIVATE_BUNDLE_JSON --output-dir datasets/cad-gis
python -m pytest -q tests/local_server/test_cad_public_export.py
```

本目录只证明公开导出边界及派生数据内容；PostgreSQL/PostGIS、Fuseki、浏览器与现场验收记录另行提供。不得把本公开小批次作为旧完整本体库的替换包。
""".encode("utf-8")


def export_public_bundle(bundle_path: Path, output_dir: Path) -> dict:
    """Export reviewed fields only; validation and serialization precede all writes."""
    bundle_path, output_dir = Path(bundle_path), Path(output_dir)
    raw = bundle_path.read_bytes()
    bundle = json.loads(raw)
    documents, counts = _public_documents(bundle)
    contents = {name: _json_bytes(value) for name, value in documents.items()}
    contents["business.nt"], triple_count = _business_rdf(documents["objects.json"]["objects"], documents["relations.json"]["relations"])
    counts["public_rdf_triples"] = triple_count
    contents["README.md"] = _readme(counts, bundle["batch_id"])
    report = {"contract": "lzo-cad-public-export/1", "source_batch_id": bundle["batch_id"], "source_bundle_sha256": hashlib.sha256(raw).hexdigest(),
              "raw_records_included": False, "counts": counts,
              "files": {name: {"sha256": hashlib.sha256(value).hexdigest(), "size_bytes": len(value)} for name, value in sorted(contents.items())}}
    contents["manifest.json"] = _json_bytes(report)
    for name, content in contents.items():
        if len(content) >= 20 * 1024 * 1024:
            raise ValueError("Public artifact exceeds 20 MiB limit: " + name)
        text = content.decode("utf-8")
        if NS + "source:" in text or re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\.runtime[\\/]", text):
            raise ValueError("Private record identity or runtime path in public artifact: " + name)
    if output_dir.exists() and any(path.name not in contents or not path.is_file() or path.is_symlink() for path in output_dir.iterdir()):
        raise ValueError("Public output directory contains unreviewed files")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in sorted(contents.items()):
        (output_dir / name).write_bytes(content)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = export_public_bundle(args.bundle, args.output_dir)
    print(json.dumps({"contract": result["contract"], "counts": result["counts"], "files": result["files"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
