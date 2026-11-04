"""Prepare source-verified local-coordinate maps without running upstream code or a DB.

The output uses GeoJSON geometry shapes with an explicit local coordinate contract.
It is NOT RFC 7946 GeoJSON, and must not be interpreted as longitude/latitude.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
from pathlib import Path
from urllib.parse import quote


REPOSITORY = "https://github.com/No1dry/farm"
COMMIT = "e08e80ce4c80ce65051ef93f1247e8797d8781f1"
NAMESPACE = "urn:lzo:fish-review:map:v1:"
SOURCE_PINS = {
    "README.md": "2c6cb8bd031e3bd0b7299856f1bb9ba82f901336",
    "THIRD_PARTY_NOTICES.md": "3b82a556f55f0caba23338d82f9601cc7fbb8ffd",
    "data/audit/entity-mapping.json": "db2713b411d07e53971c9dd758bd13d23610d60f",
    "data/spatial/drawing-entities.json": "fc6c193e45a26a2ee9820920f921e8feb5f9da67",
    "data/spatial/full-region-enrichment.json": "e3d8be5ecfc4aaf23d726aaa4f82702142a8abc0",
    "docs/data-gaps.md": "f7e224a8c19f1b642609d20d969d41163f3e6dbc",
    "docs/model-methodology.md": "41ffbf191009d78534c89e19940e8cc3a9e2c835",
    "public/models/manifest.json": "848a6961f54c5a960b9e768133b261fe3e695d45",
}
COLORS = {
    "field": "#a8c58b", "pond": "#74b4cf", "lake": "#559abf",
    "woodland": "#557d57", "settlement": "#bb9e80", "bare": "#d7c99f",
    "road": "#8a7966", "channel": "#3c88a8", "facility": "#a6704e",
    "unresolved_label": "#8f8296", "boundary": "#b63742",
}
LIMITATIONS = [
    "Full-region outlines are approximate satellite-image interpretations, not surveyed cadastral or operating boundaries.",
    "No CRS, control points, DEM or verified longitude/latitude transform is supplied.",
    "The five PDF layers have independent paper-point coordinate spaces and are not stitched to the full-region image.",
    "No synthetic device positions, generated buildings, crop state, depths, elevations or terrain relief are imported.",
    "Upstream object identities are source references. Review-graph IRIs are not production platform identity registrations.",
    "Satellite and drawing rasters are not republished. Source notices are preserved without assigning a new open-source license.",
]


def source_url(path: str) -> str:
    return f"{REPOSITORY}/blob/{COMMIT}/{quote(path, safe='/')}"


def read_verified(source_root: Path) -> tuple[dict[str, bytes], list[dict]]:
    """Verify every pinned input before creating any output/cache directory."""
    contents, metadata = {}, []
    for name, expected in SOURCE_PINS.items():
        path = source_root / name
        if not path.is_file():
            raise ValueError(f"Pinned source missing: {name}")
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if actual != expected:
            raise ValueError(f"Source Git blob mismatch: {name}")
        contents[name] = data
        metadata.append({"path": name, "git_blob_sha1": actual,
                         "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                         "source_url": source_url(name), "byte_identity_verified": True})
    return contents, metadata


def _point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in value)):
        raise ValueError("Invalid finite local coordinate")
    return list(value)


def _ring(values):
    result = [_point(p) for p in values]
    if len(result) < 3:
        raise ValueError("Polygon ring has fewer than three points")
    if result[0] != result[-1]:
        result.append(result[0].copy())
    if len({tuple(p) for p in result}) < 3:
        raise ValueError("Degenerate polygon ring")
    return result


def _geometry(value, scale=None):
    kind, coords = value["type"], value["coordinates"]
    if kind == "Polygon":
        result = {"type": kind, "coordinates": [_ring(r) for r in coords]}
    elif kind == "MultiPolygon":
        result = {"type": kind, "coordinates": [[_ring(r) for r in p] for p in coords]}
    elif kind == "LineString":
        if len(coords) < 2:
            raise ValueError("Line has fewer than two points")
        result = {"type": kind, "coordinates": [_point(p) for p in coords]}
    elif kind == "Point":
        result = {"type": kind, "coordinates": _point(coords)}
    else:
        raise ValueError(f"Unsupported source geometry: {kind}")
    if scale:
        def transform(node):
            if len(node) == 2 and all(isinstance(v, (int, float)) for v in node):
                return [node[0] * scale[0], node[1] * scale[1]]
            return [transform(v) for v in node]
        result["coordinates"] = transform(result["coordinates"])
    return result


def _source_geometry(record):
    kind = record["geometry"]["type"]
    points = record["points"]
    return _geometry({"type": kind, "coordinates": [points] if kind == "Polygon" else points})


def _local_metrics(geometry, units):
    def area(ring):
        return abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(ring, ring[1:])) / 2)
    def length(line):
        return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(line, line[1:]))
    kind, coords = geometry["type"], geometry["coordinates"]
    area_value, length_value = None, None
    if kind in ("Polygon", "MultiPolygon"):
        polygons = [coords] if kind == "Polygon" else coords
        area_value = sum(area(p[0])-sum(area(r) for r in p[1:]) for p in polygons)
        length_value = sum(length(r) for p in polygons for r in p)
    elif kind == "LineString":
        length_value = length(coords)
    return {
        "coordinate_area": {"value": area_value, "unit": units + "^2", "method": "planar_shoelace_with_holes", "data_nature": "derived_local_geometry"},
        "coordinate_length": {"value": length_value, "unit": units, "method": "planar_path_length", "data_nature": "derived_local_geometry"},
        "surveyed_area_m2": None, "surveyed_perimeter_m": None, "depth_m": None, "volume_m3": None,
    }


def build_map_data(manifest, enrichment, drawings, mapping, source_metadata=None):
    """Project explicit source records; synthetic records never supply identities or geometry."""
    metadata = {r["path"]: r for r in (source_metadata or [])}
    def evidence(path, pointer, **extra):
        result = {"path": path, "git_blob_sha1": SOURCE_PINS.get(path), "sha256": metadata.get(path, {}).get("sha256"),
                  "record_pointer": pointer, "source_url": source_url(path)}
        result.update(extra)
        return result
    identities = {}
    for index, record in enumerate(mapping["entities"]):
        if record.get("dataset") != "real" or record.get("data_nature") != "imported_unverified":
            continue
        for sid in record["spatial_ids"]:
            identities.setdefault(sid, []).append((index, record))
    def identity(sid):
        values = identities.get(sid, [])
        if len(values) != 1:
            raise ValueError(f"Missing or ambiguous source identity: {sid}")
        index, record = values[0]
        if record["iri"] != "urn:lzo:object:" + record["resource_id"]:
            raise ValueError(f"Source identity IRI mismatch: {sid}")
        return index, record
    refined = {}
    for index, record in enumerate(enrichment["records"]):
        if record["id"] in refined:
            raise ValueError("Duplicate enrichment record id")
        refined[record["id"]] = (index, record)
    scale = (enrichment["native_to_reference"]["x_scale"], enrichment["native_to_reference"]["y_scale"])
    if any(not math.isfinite(n) or n <= 0 for n in scale):
        raise ValueError("Invalid image scale")
    canvas = manifest["coordinate_system"]["source_canvas"]
    source = {"repository": REPOSITORY, "commit": COMMIT, "url": f"{REPOSITORY}/commit/{COMMIT}"}
    layers = [{"id": "full", "label": "总方案全域 · 卫星图判读", "coordinate_space": "LOCAL_IMAGE_APPROX",
               "units": "reference_image_pixel", "viewBox": [0, 0, *canvas], "axis": {"x": "right", "y": "down"},
               "crs": None, "georeferenced": False, "background_url": None, "features": []}]
    for drawing in drawings["drawings"]:
        layers.append({"id": drawing["asset_id"], "label": drawing["label"], "coordinate_space": "PDF_LANDSCAPE_LOCAL",
                       "units": "pt", "viewBox": [0, 0, *drawing["page_size_pt"]], "axis": {"x": "right", "y": "down"},
                       "crs": None, "georeferenced": False, "background_url": None, "features": [],
                       "source_file": drawing["source_file"], "source_sha256": drawing["source_hash"]})
    by_layer = {layer["id"]: layer for layer in layers}
    objects, seen = [], set()
    def add(sid, label, kind, asset_id, geometry, source_evidence, boundary_status, extra):
        if sid in seen:
            raise ValueError(f"Duplicate spatial identity: {sid}")
        seen.add(sid)
        mapping_index, source_identity = identity(sid)
        source_evidence.append(evidence("data/audit/entity-mapping.json", f"/entities/{mapping_index}"))
        layer = by_layer[asset_id]
        object_iri = NAMESPACE + "object:" + quote(sid, safe="-._~")
        item = {"id": sid, "object_iri": object_iri,
                "canonical_key": f"No1dry/farm@{COMMIT}:{asset_id}:{sid}",
                "label": label, "kind": kind, "class_iri": NAMESPACE + "class:" + ''.join(p.title() for p in kind.split('_')),
                "asset_id": asset_id, "parent_iri": NAMESPACE + "layer:" + asset_id,
                "geometry": geometry, "coordinate_space": layer["coordinate_space"], "coordinate_units": layer["units"],
                "crs": None, "georeferenced": False, "data_nature": "imported_unverified",
                "source_object_iri": source_identity["iri"], "source_resource_id": source_identity["resource_id"],
                "source_key": copy.deepcopy(source_identity.get("source_key")),
                "source_evidence_ids": copy.deepcopy(source_identity.get("evidence_ids", [])),
                "source_evidence": source_evidence, "boundary_status": boundary_status,
                "metrics": _local_metrics(geometry, layer["units"]),
                "relations": [{"predicate": NAMESPACE + "inLayer", "object": NAMESPACE + "layer:" + asset_id}],
                "production_identity_registered": False}
        item.update(extra)
        objects.append(item)
        props = {key: copy.deepcopy(value) for key, value in item.items() if key not in {"geometry", "original_geometry"}}
        props.update(color=COLORS[kind], source_spatial_id=sid, object_class_iri=item["class_iri"])
        layer["features"].append({"type": "Feature", "id": sid, "geometry": geometry, "properties": props})
    for index, record in enumerate(manifest["objects"]):
        if record["asset_id"] != "full":
            continue
        sid = record["spatial_id"]
        original = _source_geometry(record)
        geometry = original
        refs = [evidence("public/models/manifest.json", f"/objects/{index}"),
                evidence(enrichment["source_file"], None, sha256=enrichment["source_sha256"], role="original_image_not_republished")]
        geometry_provenance = {"source_path": "public/models/manifest.json", "source_record_id": sid,
                               "method": "source_reference_image_points", "georeferenced": False}
        override = record.get("appearance_geometry_override")
        if override:
            if override["record_id"] not in refined:
                raise ValueError(f"Missing observed geometry override: {sid}")
            ri, refinement = refined[override["record_id"]]
            if refinement.get("source_status") != "observed":
                raise ValueError(f"Geometry override is not observed: {sid}")
            if refinement.get("parent_spatial_id") != sid:
                raise ValueError(f"Geometry override parent differs: {sid}")
            if refinement.get("coordinate_units") != "native_image_pixels":
                raise ValueError(f"Unknown observed coordinate units: {sid}")
            geometry = _geometry(refinement["geometry"], scale)
            refs.append(evidence("data/spatial/full-region-enrichment.json", f"/records/{ri}", source_record_id=refinement["id"]))
            geometry_provenance = {"source_path": "data/spatial/full-region-enrichment.json", "source_record_id": refinement["id"],
                                   "method": "observed_native_pixels_scaled_to_reference_pixels", "x_scale": scale[0], "y_scale": scale[1],
                                   "source_geometry": copy.deepcopy(refinement["geometry"]), "georeferenced": False}
        add(sid, record["name"], record["kind"], "full", geometry, refs, "approximate_visual_outline" if geometry["type"] != "LineString" else "approximate_visual_centerline",
            {"region": record.get("region"), "original_geometry": original, "geometry_provenance": geometry_provenance,
             "source_statement": record.get("source"), "source_model_metrics": {
                 "area_m2": record.get("model_area_m2"), "length_m": record.get("model_length_m"),
                 "data_nature": "approximate_screenshot_scale_model", "is_field_measurement": False,
                 "scale_metres_per_reference_pixel": manifest["coordinate_system"].get("metres_per_pixel")}})
    for index, record in enumerate(drawings["records"]):
        kind = "unresolved_label" if record.get("identity_scope") == "unresolved_drawing_label" else record["kind"]
        geometry = _geometry(record["geometry"])
        refs = [evidence("data/spatial/drawing-entities.json", f"/records/{index}"),
                evidence(record["source_file"], None, sha256=record["source_hash"], page=record.get("source_page"), role="original_drawing_not_republished")]
        add(record["representation_id"], record["label"], kind, record["asset_id"], geometry, refs, record["boundary_status"],
            {"region": record.get("region"), "source_representation_id": record.get("source_representation_id"),
             "source_code": record.get("original_code"), "source_geometry_evidence": copy.deepcopy(record.get("source_evidence", [])),
             "geometry_provenance": {"source_path": "data/spatial/drawing-entities.json", "source_record_id": record["representation_id"], "method": "preserved_source_paper_geometry"},
             "ledger_area": {"value": record.get("area_original"), "unit": record.get("area_unit"), "inferred_unit": record.get("inferred_unit"),
                             "inference_status": record.get("inference_status"), "data_nature": "source_value_unit_unconfirmed" if record.get("area_unit") is None else "source_value"},
             "documented_dimensions": copy.deepcopy(record.get("documented_dimensions", [])),
             "link_verified_in_source": record.get("link_verified", False)})
    redline = _geometry({"type": "Polygon", "coordinates": [manifest["boundary"]["points"]]})
    layers[0]["features"].append({"type": "Feature", "id": "FULL-REDLINE", "geometry": redline,
                                  "properties": {"label": "来源图红线（概略，非确权边界）", "kind": "boundary", "color": COLORS["boundary"],
                                                 "object_iri": None, "source_spatial_id": None, "data_nature": "imported_unverified",
                                                 "boundary_status": manifest["boundary"]["precision"],
                                                 "source_evidence": [evidence("public/models/manifest.json", "/boundary")],
                                                 "metrics": _local_metrics(redline, layers[0]["units"])}})
    spaces = [{k: copy.deepcopy(v) for k, v in layer.items() if k != "features"} for layer in layers]
    objects_bundle = {"schema_version": "farm-map-objects/1", "source": source, "coordinate_spaces": spaces,
                      "objects": objects, "limitations": LIMITATIONS}
    map_bundle = {"schema_version": "farm-local-map/1", "source": source, "crs": None, "rfc7946": False,
                  "coordinate_contract": "GeoJSON geometry shapes in explicit local image/paper spaces; not longitude/latitude.",
                  "layers": layers, "limitations": LIMITATIONS}
    return objects_bundle, map_bundle


def render_svg(layer):
    def path_line(points, close=False):
        return "M" + " L".join(f"{p[0]:.8f},{p[1]:.8f}" for p in points) + (" Z" if close else "")
    x, y, width, height = layer["viewBox"]
    stroke = max(width, height) / 1000
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {width} {height}" role="img">',
             '<title>' + html.escape(layer["label"]) + '</title>',
             '<desc>Source-derived local coordinates. No georeferencing; no satellite raster background.</desc>',
             f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#f4f5ef"/>']
    for feature in layer["features"]:
        props, geometry = feature["properties"], feature["geometry"]
        color = html.escape(props["color"], quote=True)
        boundary = props["kind"] == "boundary"
        attrs = f'data-feature-id="{html.escape(feature["id"], quote=True)}" data-object-iri="{html.escape(props.get("object_iri") or "", quote=True)}"'
        title = '<title>' + html.escape(props["label"]) + '</title>'
        kind, coords = geometry["type"], geometry["coordinates"]
        if kind == "Point":
            parts.append(f'<circle {attrs} cx="{coords[0]}" cy="{coords[1]}" r="{stroke*2}" fill="{color}">{title}</circle>')
        else:
            if kind == "LineString":
                d, fill = path_line(coords), "none"
            else:
                polygons = [coords] if kind == "Polygon" else coords
                d = " ".join(path_line(r, True) for polygon in polygons for r in polygon)
                fill = "none" if boundary else color
            dash = ' stroke-dasharray="7 4"' if boundary else ''
            parts.append(f'<path {attrs} d="{d}" fill="{fill}" fill-rule="evenodd" stroke="{color if boundary or kind == "LineString" else "#536250"}" stroke-width="{stroke*(1.8 if boundary else .6)}"{dash}>{title}</path>')
    return "\n".join(parts + ["</svg>"]) + "\n"


def prepare(source_root: Path, project_root: Path):
    contents, metadata = read_verified(source_root)
    data = lambda name: json.loads(contents[name])
    objects, maps = build_map_data(data("public/models/manifest.json"), data("data/spatial/full-region-enrichment.json"),
                                   data("data/spatial/drawing-entities.json"), data("data/audit/entity-mapping.json"), metadata)
    if len(objects["objects"]) != 284 or len(maps["layers"]) != 6 or len(maps["layers"][0]["features"]) != 122:
        raise ValueError("Pinned source coverage differs from the reviewed 121+163 objects")
    # All source checks and projection checks have passed; writes are confined to the target project.
    target = project_root.resolve()
    dataset = target / "datasets/farm-map"
    view_data = target / "docs/fish/ontology-review/data"
    cache = target / ".runtime/source-imports/no1dry-farm" / COMMIT
    outputs = {}
    def save(path, value, compact=False):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":") if compact else None,
                          indent=None if compact else 2, allow_nan=False).encode("utf-8") + b"\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        outputs[path.relative_to(target).as_posix()] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    save(dataset / "map-objects.json", objects, compact=True)
    save(dataset / "map-features.json", maps, compact=True)
    save(view_data / "map-features.json", maps, compact=True)
    for layer in maps["layers"]:
        svg = render_svg(layer).encode("utf-8")
        path = dataset / (layer["id"] + ".svg")
        path.write_bytes(svg)
        outputs[path.relative_to(target).as_posix()] = {"sha256": hashlib.sha256(svg).hexdigest(), "bytes": len(svg)}
    notices = contents["THIRD_PARTY_NOTICES.md"]
    (dataset / "THIRD_PARTY_NOTICES.upstream.md").write_bytes(notices)
    outputs["datasets/farm-map/THIRD_PARTY_NOTICES.upstream.md"] = {
        "sha256": hashlib.sha256(notices).hexdigest(), "bytes": len(notices)}
    for name, body in contents.items():
        path = cache / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    source_report = {
        "schema_version": "farm-map-source-manifest/1", "repository": REPOSITORY, "commit": COMMIT,
        "upstream_release": "v0.6.0", "verification": "Git blob SHA-1 from the pinned public commit, plus locally computed SHA-256 for every consumed input",
        "inputs": metadata, "outputs": outputs,
        "license": {"project_license": None, "status": "no_unified_license_declared", "notice_file": "THIRD_PARTY_NOTICES.upstream.md",
                    "reuse_basis": "User explicitly requested reuse of project GIS contours; retain original source terms and attribution.",
                    "raster_republished": False, "new_license_assigned": False},
        "counts": {"full_region_objects": 121, "drawing_representations": 163, "drawing_field_polygons": 100,
                   "drawing_pond_polygons": 20, "drawing_unknown_boundary_anchors": 21, "layers": 6,
                   "review_objects": 284, "redline_overlays": 1,
                   "observed_refined_geometries": sum(o.get("geometry_provenance", {}).get("method") == "observed_native_pixels_scaled_to_reference_pixels" for o in objects["objects"])},
        "limitations": LIMITATIONS, "database_writes": 0, "upstream_files_modified": 0,
    }
    save(dataset / "source-manifest.json", source_report)
    return {"status": "prepared", "source_commit": COMMIT, "counts": source_report["counts"], "database_writes": 0,
            "outputs": list(outputs), "rfc7946": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path, help="Read-only upstream source checkout or extracted source tree")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_root, args.project_root), ensure_ascii=False))


if __name__ == "__main__":
    main()
