"""Lossless intake tests use tiny synthetic, real SQLite/CSV/JSON files."""
import base64
import hashlib
import json
import sqlite3
import struct
from pathlib import Path

import pytest

from local_server.spatial_source import prepare_cad_bundle


def manifest_for(root, paths):
    files = []
    for name in paths:
        data = (root / name).read_bytes()
        files.append({"path": name, "commit": "a" * 40,
                      "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
                      "size_bytes": len(data)})
    return {"repository": "example/synthetic", "source_files": files}


def test_gpkg_retains_all_tables_columns_rows_and_original_geometry(tmp_path):
    path = tmp_path / "unknown.gpkg"
    binary = b"GP\x00\x01" + struct.pack("<i", -1) + struct.pack("<BIddd", 1, 1001, 501000, 3300000, 27.125)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER, definition TEXT)")
        db.execute("INSERT INTO gpkg_spatial_ref_sys VALUES ('Undefined', -1, 'undefined')")
        db.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, geometry_type_name TEXT, srs_id INTEGER, z INTEGER, m INTEGER)")
        db.execute("INSERT INTO gpkg_geometry_columns VALUES ('survey', 'geom', 'POINT', -1, 1, 0)")
        db.execute("CREATE TABLE survey (id INTEGER, geom BLOB, original_height REAL, note TEXT, nullable TEXT)")
        db.execute("INSERT INTO survey VALUES (1, ?, 27.125, 'unverified height', NULL)", (binary,))
        db.execute("INSERT INTO survey VALUES (2, ?, 30.5, 'bad geometry retained', NULL)", (b"broken",))
        db.execute("CREATE TABLE source_metadata (name TEXT, content BLOB)")
        db.execute("INSERT INTO source_metadata VALUES ('vendor', ?)", (b"\x00\xff",))
        db.execute("CREATE TABLE empty_source_table (id INTEGER, extra TEXT)")
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, [path.name]))
    tables = {row["name"]: row for row in bundle["source_tables"]}
    assert set(tables) == {"gpkg_spatial_ref_sys", "gpkg_geometry_columns", "survey", "source_metadata", "empty_source_table"}
    assert tables["survey"]["columns"] == ["id", "geom", "original_height", "note", "nullable"]
    assert tables["survey"]["row_count"] == 2
    assert tables["empty_source_table"]["row_count"] == 0
    records = [row for row in bundle["source_records"] if row["table"] == "survey"]
    assert records[0]["payload"] == {"id": 1, "geom": {"__type__": "bytes", "base64": base64.b64encode(binary).decode()}, "original_height": 27.125, "note": "unverified height", "nullable": None}
    assert records[0]["geometry"]["coordinates"] == [501000.0, 3300000.0, 27.125]
    assert records[0]["source_srid"] == -1
    assert records[0]["status"] == "quarantined"
    assert "unknown_crs" in records[0]["issues"]
    assert records[1]["status"] == "quarantined"
    assert bundle["map"]["features"] == []
    assert len(bundle["source_records"]) == 5
    assert bundle["source_files"][0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads((tmp_path / "out" / "bundle.json").read_text(encoding="utf-8")) == bundle


def test_csv_strings_json_metadata_and_report_text_are_lossless_and_stable(tmp_path):
    (tmp_path / "values.csv").write_text('code,height,empty,note\n001,027.00,,"two\nlines"\n002,unknown,,末行\n', encoding="utf-8-sig", newline="")
    (tmp_path / "metadata.json").write_text(json.dumps({"units": {"height": "m"}, "rows": [{"code": "001", "private": "complete source"}], "declared": None}), encoding="utf-8")
    (tmp_path / "report.md").write_text("# Report\n候选坐标\n", encoding="utf-8", newline="")
    manifest = manifest_for(tmp_path, ["values.csv", "metadata.json", "report.md"])
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest)
    csv_rows = [r["payload"] for r in bundle["source_records"] if r["table"] == "csv"]
    assert csv_rows == [{"code": "001", "height": "027.00", "empty": "", "note": "two\nlines"}, {"code": "002", "height": "unknown", "empty": "", "note": "末行"}]
    assert next(r["payload"] for r in bundle["source_records"] if r["table"] == "$document")["units"] == {"height": "m"}
    assert next(r["payload"] for r in bundle["source_records"] if r["table"] == "text")["text"] == "# Report\n候选坐标\n"
    repeated = prepare_cad_bundle(tmp_path, tmp_path / "again", {**manifest, "source_files": list(reversed(manifest["source_files"]))})
    assert bundle == repeated


@pytest.mark.parametrize("field,value", [("git_blob_sha", "0" * 40), ("size_bytes", 123456)])
def test_mismatched_source_fails_before_output_is_written(tmp_path, field, value):
    (tmp_path / "value.csv").write_text("a\n1\n", encoding="utf-8")
    manifest = manifest_for(tmp_path, ["value.csv"])
    manifest["source_files"][0][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        prepare_cad_bundle(tmp_path, tmp_path / "out", manifest)
    assert not (tmp_path / "out" / "bundle.json").exists()


def test_source_path_must_stay_inside_input_directory(tmp_path):
    with pytest.raises(ValueError, match="path"):
        prepare_cad_bundle(tmp_path, tmp_path / "out", {"source_files": [{"path": "../escape.csv", "git_blob_sha": "0" * 40, "size_bytes": 0}]})


def test_cad_identity_duplicate_evidence_text_anchors_and_camera_remain_distinct(tmp_path):
    geometry = {"type": "Polygon", "coordinates": [[[114, 30], [114.002, 30], [114.002, 30.002], [114, 30.002], [114, 30]]]}
    registration = {"villages": [{"code": "A", "name": "Village", "drawing": "A.dxf"}], "items": [
        {"code": "CAD-A-T01", "name": "Field", "kind": "field", "drawing": "A.dxf", "handle": "10", "geometry": geometry, "source_note": "candidate"},
        {"code": "CAD-A-BZ01", "name": "Pump", "kind": "facility", "drawing": "A.dxf", "handle": "20", "geometry": None},
        {"code": "CAD-A-SZ01", "name": "Gate", "kind": "facility", "drawing": "A.dxf", "handle": "21", "geometry": None}]}
    reference = {"type": "FeatureCollection", "metadata": {"source_crs": "EPSG:4547", "target_crs": "EPSG:4326"}, "features": [
        {"type": "Feature", "id": "A__10", "geometry": geometry, "properties": {"category": "land", "cad_file": "A.dxf", "handle": "10", "measure_value": 123, "measure_unit": "平方米", "crs_status": "UNKNOWN"}},
        {"type": "Feature", "id": "A__30", "geometry": {"type": "LineString", "coordinates": [[114, 30], [114.001, 30]]}, "properties": {"category": "road", "cad_file": "A.dxf", "handle": "30"}}]}
    anchors = {"positions": [{"code": "CAD-A-BZ01", "name": "Pump", "geometry": {"type": "Point", "coordinates": [114.001, 30.001]}, "source_note": "text label only"}], "unmatched": ["CAD-A-SZ01"]}
    cameras = [{"类型": "摄像头图标", "E": 501000, "N": 3300000, "经度": 114.001, "纬度": 30.001}]
    documents = {"data/cad-reference/registration-dataset.json": registration,
                 "data/cad-reference/completion-reference.json": reference,
                 "data/cad-reference/facility-label-positions.json": anchors,
                 "定位验证成果/监控摄像头39处.json": cameras}
    for name, payload in documents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, list(documents)))
    assert len(bundle["objects"]) == 6
    field = next(o for o in bundle["objects"] if o["kind"] == "field")
    assert field["iri"] == "urn:lzo:cad-gis:v1:instance:CAD-A-T01"
    assert len(field["source_refs"]) == 2
    assert field["attributes"]["source_values"][1]["measure_value"] == 123
    assert bundle["quality"]["duplicate_source_references"] == 1
    assert len(bundle["map"]["display_features"]) == 1
    pump = next(o for o in bundle["objects"] if o["id"] == "CAD-A-BZ01")
    assert pump["position_status"] == "candidate_text_anchor"
    camera = next(o for o in bundle["objects"] if o["kind"] == "camera")
    assert camera["attributes"]["device_iri"] is None
    assert camera["attributes"]["depth_m"] is None
    assert camera["position_status"] == "candidate_cad_symbol"
    assert camera["iri"] != pump["iri"]
    public_camera = next(o for o in bundle["map"]["features"] if o["iri"] == camera["iri"])
    assert public_camera["attributes"]["area_memberships"][0]["area_iri"] == field["iri"]
    assert public_camera["attributes"]["area_memberships"][0]["evidence"]["algorithm"] == "shapely.covers"
    assert public_camera["attributes"]["area_memberships"][0]["evidence"]["business_ownership"] is False
    assert any(r["subject"] == camera["iri"] and r["object"] == field["iri"] and r["predicate"].endswith("spatiallyWithinCandidate") and r["evidence"]["algorithm"] == "shapely.covers" for r in bundle["relations"])
    assert any(r["subject"] == field["iri"] and r["predicate"].endswith("sourceDiagramRegion") for r in bundle["relations"])
    assert all("source_record_ids" not in item for item in bundle["map"]["features"])
    assert "source:" not in json.dumps(bundle["map"])
    assert next(o for o in bundle["map"]["unlocated"] if o["id"] == "CAD-A-SZ01")["geometry"] is None


def test_duplicate_csv_headers_and_ragged_rows_do_not_discard_values(tmp_path):
    (tmp_path / "odd.csv").write_text("code,code\na,b,c\n001\n", encoding="utf-8")
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, ["odd.csv"]))
    assert [r["payload"] for r in bundle["source_records"]] == [
        {"__columns__": ["code", "code"], "__values__": ["a", "b", "c"]},
        {"__columns__": ["code", "code"], "__values__": ["001"]}]


def test_local_undefined_gpkg_srs_is_quarantined_even_without_row_crs_status(tmp_path):
    binary = b"GP\x00\x01" + struct.pack("<i", 99999) + struct.pack("<BIdd", 1, 1, 501000, 3300000)
    with sqlite3.connect(tmp_path / "local.gpkg") as db:
        db.execute("CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER, definition TEXT)")
        db.execute('INSERT INTO gpkg_spatial_ref_sys VALUES (?, 99999, ?)', ('Undefined SRS', 'LOCAL_CS["Undefined SRS",LOCAL_DATUM["unknown",32767]]'))
        db.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER)")
        db.execute("INSERT INTO gpkg_geometry_columns VALUES ('points','geom',99999)")
        db.execute("CREATE TABLE points (geom BLOB)")
        db.execute("INSERT INTO points VALUES (?)", (binary,))
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, ["local.gpkg"]))
    point = next(r for r in bundle["source_records"] if r["table"] == "points")
    assert point["status"] == "quarantined"
    assert "unknown_crs" in point["issues"]
    assert point["geometry"]["coordinates"] == [501000.0, 3300000.0]


def test_cli_prepares_verified_bundle_and_emits_counts_only(tmp_path):
    import subprocess
    import sys
    (tmp_path / "values.csv").write_text("secret\nPRIVATE-SOURCE-CONTENT\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_for(tmp_path, ["values.csv"])), encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "prepare_cad_gis.py"
    result = subprocess.run([sys.executable, str(script), "--inputs-dir", str(tmp_path), "--output-dir", str(tmp_path / "out"), "--source-manifest", str(manifest_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["counts"]["source_records"] == 1
    assert "PRIVATE-SOURCE-CONTENT" not in result.stdout
    assert (tmp_path / "out" / "bundle.json").exists()


def test_invalid_json_geometry_retains_source_and_reports_positioning_shortfall(tmp_path):
    path = tmp_path / "data/cad-reference/registration-dataset.json"
    path.parent.mkdir(parents=True)
    geometry = {"type": "Polygon", "coordinates": [[[114, 30], [114.002, 30.002], [114, 30.002], [114.002, 30], [114, 30]]]}
    path.write_text(json.dumps({"items": [{"code": "CAD-BAD", "kind": "field", "name": "invalid", "drawing": "A.dxf", "handle": "1", "geometry": geometry}]}), encoding="utf-8")
    manifest = manifest_for(tmp_path, ["data/cad-reference/registration-dataset.json"])
    manifest["registration"] = {"objects": 1, "fields": 1, "ponds": 0, "facilities": 0, "polygon_geometries": 1}
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest)
    record = next(r for r in bundle["source_records"] if r["table"] == "/items")
    assert record["status"] == "quarantined"
    assert record["payload"]["geometry"] == geometry
    assert next(t for t in bundle["source_tables"] if t["name"] == "/items")["quarantined_count"] == 1
    assert bundle["objects"][0]["geometry"] == geometry
    assert bundle["map"]["features"] == []
    assert bundle["map"]["unlocated"][0]["position_status"] == "invalid_geometry_quarantined"
    assert bundle["quality"]["source_expectations"]["positioned_polygons"] == {"expected": 1, "actual": 0, "delta": -1, "status": "mismatch"}


def test_an_existing_output_batch_cannot_be_replaced_by_another_source(tmp_path):
    path = tmp_path / "values.csv"
    path.write_text("code\na\n", encoding="utf-8")
    prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, ["values.csv"]))
    before = (tmp_path / "out" / "bundle.json").read_bytes()
    path.write_text("code\nb\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different batch"):
        prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, ["values.csv"]))
    assert (tmp_path / "out" / "bundle.json").read_bytes() == before
    assert (tmp_path / "out" / "source-files" / "values.csv").read_text(encoding="utf-8") == "code\na\n"


def test_explicit_gpkg_quarantine_table_stays_quarantined_with_known_srid(tmp_path):
    binary = b"GP\x00\x01" + struct.pack("<i", 4326) + struct.pack("<BIdd", 1, 1, 114, 30)
    name = "隔离_设施未确认_设施候选"
    with sqlite3.connect(tmp_path / "candidate.gpkg") as db:
        db.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER)")
        db.execute("INSERT INTO gpkg_geometry_columns VALUES (?,'geom',4326)", (name,))
        db.execute('CREATE TABLE "' + name + '" (geom BLOB, note TEXT)')
        db.execute('INSERT INTO "' + name + '" VALUES (?,?)', (binary, "unverified facility"))
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, ["candidate.gpkg"]))
    record = next(row for row in bundle["source_records"] if row["table"] == name)
    assert record["status"] == "quarantined"
    assert "source_quarantine_table" in record["issues"]
    assert record["geometry"]["coordinates"] == [114.0, 30.0]


def test_point_multi_hit_memberships_reach_public_map_without_unique_ownership(tmp_path):
    geometry = {"type": "Polygon", "coordinates": [[[114, 30], [114.002, 30], [114.002, 30.002], [114, 30.002], [114, 30]]]}
    registration = {"items": [{"code": "CAD-A", "kind": "field", "drawing": "A.dxf", "handle": "A", "geometry": geometry},
                               {"code": "CAD-B", "kind": "pond", "drawing": "A.dxf", "handle": "B", "geometry": geometry}]}
    documents = {"data/cad-reference/registration-dataset.json": registration,
                 "定位验证成果/监控摄像头39处.json": [{"经度": 114.001, "纬度": 30.001}]}
    for name, data in documents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, list(documents)))
    camera = next(row for row in bundle["map"]["features"] if row["kind"] == "camera")
    memberships = camera["attributes"]["area_memberships"]
    assert {row["area_iri"] for row in memberships} == {"urn:lzo:cad-gis:v1:instance:CAD-A", "urn:lzo:cad-gis:v1:instance:CAD-B"}
    assert all(row["evidence"]["hit_count"] == 2 and row["evidence"]["ambiguous"] is True for row in memberships)
    assert all(row["evidence"]["business_ownership"] is False for row in memberships)


def test_csv_unknown_coordinates_and_unverified_heights_are_quarantined_as_strings(tmp_path):
    (tmp_path / "survey.csv").write_text("原始X,原始Y,原始Z,Z审核状态,坐标参考,垂直高程基准\n501000.00,3300000.00,027.125,未确认,UNKNOWN,未确认\n", encoding="utf-8", newline="")
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, ["survey.csv"]))
    record = bundle["source_records"][0]
    assert record["status"] == "quarantined"
    assert "unknown_crs" in record["issues"]
    assert "unverified_vertical_datum" in record["issues"]
    assert record["payload"]["原始Z"] == "027.125"
    assert bundle["map"]["features"] == []


def test_nonfinite_gpkg_geometry_is_quarantined_without_aborting_lossless_bundle(tmp_path):
    binary = b"GP\x00\x01" + struct.pack("<i", 4326) + struct.pack("<BIdd", 1, 1, float("inf"), 30)
    with sqlite3.connect(tmp_path / "nonfinite.gpkg") as db:
        db.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER)")
        db.execute("INSERT INTO gpkg_geometry_columns VALUES ('points','geom',4326)")
        db.execute("CREATE TABLE points (geom BLOB, note TEXT)")
        db.execute("INSERT INTO points VALUES (?,?)", (binary, "retain invalid source"))
    bundle = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest_for(tmp_path, ["nonfinite.gpkg"]))
    record = next(row for row in bundle["source_records"] if row["table"] == "points")
    assert record["status"] == "quarantined"
    assert "nonfinite_geometry_coordinate" in record["issues"]
    assert record["geometry"] is None
    assert record["decoded_geometry"]["coordinates"] == [{"__type__": "float", "value": "Infinity"}, 30.0]
    assert base64.b64decode(record["payload"]["geom"]["base64"]) == binary
    assert (tmp_path / "out" / "source-files" / "nonfinite.gpkg").read_bytes() == (tmp_path / "nonfinite.gpkg").read_bytes()
    assert json.loads((tmp_path / "out" / "bundle.json").read_text(encoding="utf-8")) == bundle


@pytest.mark.parametrize("change", ["repository", "file_metadata", "expected_counts"])
def test_existing_batch_rejects_changed_provenance_or_metadata_even_with_same_files(tmp_path, change):
    (tmp_path / "values.csv").write_text("code\na\n", encoding="utf-8")
    manifest = manifest_for(tmp_path, ["values.csv"])
    prepare_cad_bundle(tmp_path, tmp_path / "out", manifest)
    before = {p.relative_to(tmp_path / "out"): p.read_bytes() for p in (tmp_path / "out").rglob("*") if p.is_file()}
    if change == "repository":
        manifest["repository"] = "different/repository"
    elif change == "file_metadata":
        manifest["source_files"][0]["url"] = "https://example.test/changed-source"
    else:
        manifest["registration"] = {"objects": 1}
    with pytest.raises(ValueError, match="immutable"):
        prepare_cad_bundle(tmp_path, tmp_path / "out", manifest)
    assert {p.relative_to(tmp_path / "out"): p.read_bytes() for p in (tmp_path / "out").rglob("*") if p.is_file()} == before


def test_existing_identical_batch_retry_is_byte_idempotent(tmp_path):
    (tmp_path / "values.csv").write_text("code\na\n", encoding="utf-8")
    manifest = manifest_for(tmp_path, ["values.csv"])
    first = prepare_cad_bundle(tmp_path, tmp_path / "out", manifest)
    before = {p.relative_to(tmp_path / "out"): p.read_bytes() for p in (tmp_path / "out").rglob("*") if p.is_file()}
    assert prepare_cad_bundle(tmp_path, tmp_path / "out", manifest) == first
    assert {p.relative_to(tmp_path / "out"): p.read_bytes() for p in (tmp_path / "out").rglob("*") if p.is_file()} == before
