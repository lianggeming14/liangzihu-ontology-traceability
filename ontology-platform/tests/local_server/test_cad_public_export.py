"""Public exporter boundary tests use synthetic source/candidate evidence."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from scripts.export_cad_gis_public import export_public_bundle


NS = "urn:lzo:cad-gis:v1:"
PRIVATE = "PRIVATE-PAYLOAD-MUST-NOT-BE-EXPORTED"


def candidate_bundle():
    file = {"file_id": "f" * 64, "id": "f" * 64, "path": "data/geometry.json", "commit": "a" * 40,
            "git_blob_sha": "b" * 40, "sha256": "c" * 64, "size_bytes": 123,
            "url": "https://github.com/example/source/blob/" + "a" * 40 + "/data/geometry.json",
            "original_path": "C:/PRIVATE-RUNTIME/source-files/data/geometry.json", "payload": PRIVATE}
    ref = {**file, "table": "/items", "row_number": 1, "source_record_iri": NS + "source:secret"}
    field = {"id": "CAD-1", "iri": NS + "instance:CAD-1", "class_iri": NS + "class:field", "class_key": "field",
             "label": "Candidate field", "kind": "field", "layer_id": "field", "nature": "cad_candidate_unverified",
             "geometry": {"type": "Polygon", "coordinates": [[[114, 30], [114.001, 30], [114.001, 30.001], [114, 30]]]},
             "source_refs": [ref], "source_record_ids": [NS + "source:secret"], "position_status": "candidate_approximate",
             "attributes": {"depth_m": None, "private_payload": PRIVATE, "area_memberships": [],
                            "computed_measurements": {"area_m2": 100, "perimeter_m": 40, "length_m": None, "method": "geodesic", "units": {"area": "m2", "perimeter": "m", "private": PRIVATE}, "assumptions": "candidate", "raw_payload": PRIVATE},
                            "source_values": [{"measure_value": "00100.00", "measure_unit": "m2", "private": PRIVATE}]}}
    camera = copy.deepcopy(field)
    camera.update({"id": "camera-1", "iri": NS + "instance:camera-1", "class_iri": NS + "class:camera", "class_key": "camera", "kind": "camera", "layer_id": "camera",
                   "geometry": {"type": "Point", "coordinates": [114.0005, 30.0002]}, "position_status": "candidate_cad_symbol"})
    evidence = {"algorithm": "shapely.covers", "business_ownership": False, "hit_count": 1, "ambiguous": False, "source_refs": [ref], "private_payload": PRIVATE}
    camera["attributes"] = {"device_iri": None, "depth_m": None, "area_memberships": [{"area_iri": field["iri"], "evidence": evidence, "status": "derived_candidate_spatial_evidence", "payload": PRIVATE}]}
    relation = {"subject": camera["iri"], "predicate": NS + "property:spatiallyWithinCandidate", "object": field["iri"], "evidence": evidence, "status": "derived_candidate_spatial_evidence", "raw_payload": PRIVATE}
    face = {"id": "face-1", "geometry": field["geometry"], "object_iris": [field["iri"]], "kind": "field", "layer_id": "field", "conflict": False, "payload": PRIVATE}
    return {"contract": "lzo-cad-batch/1", "batch_id": "d" * 64, "namespace": NS, "objects": [field, camera], "relations": [relation],
            "source_files": [file], "source_tables": [{"file_id": file["file_id"], "name": "/items", "columns": ["code", "geometry"], "row_count": 2, "received_count": 2, "quarantined_count": 0, "column_definitions": [{"default": PRIVATE}]}],
            "source_records": [{"id": NS + "source:secret", "payload": {"raw": PRIVATE}, "geometry": {"type": "Point", "coordinates": [999999, 999999]}}],
            "quality": {"private_payload": PRIVATE}, "counts": {"private": PRIVATE},
            "map": {"contract": "lzo-spatial-map/2", "crs": {"display_srid": 4326, "registration_status": "candidate_approximate", "original_cad_crs_status": "UNKNOWN", "display_z": 0, "runtime_path": "C:/PRIVATE-RUNTIME"},
                    "features": [field, camera], "unlocated": [], "display_features": [face], "bounds": [114, 30, 114.001, 30.001],
                    "layers": [{"id": "field", "label": "Fields", "visible": True, "payload": PRIVATE}],
                    "quality": {"area_tolerance_m2": 1e-6, "conflict_faces": [], "invalid_geometry": [], "source_expectations": {}, "private_payload": PRIVATE}, "raw_records": PRIVATE}}


def write_bundle(tmp_path, bundle):
    path = tmp_path / "private-bundle.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return path


def test_public_export_whitelist_preserves_geometry_measurement_links_but_drops_private_payload(tmp_path):
    source = candidate_bundle()
    report = export_public_bundle(write_bundle(tmp_path, source), tmp_path / "public")
    files = {path.name: path.read_text(encoding="utf-8") for path in (tmp_path / "public").iterdir()}
    assert {"map.json", "objects.json", "relations.json", "provenance.json", "business.nt", "manifest.json", "README.md"} == set(files)
    combined = "\n".join(files.values())
    assert PRIVATE not in combined and "C:/PRIVATE-RUNTIME" not in combined and NS + "source:" not in combined
    objects = json.loads(files["objects.json"])["objects"]
    assert objects[0]["geometry"] == source["objects"][0]["geometry"]
    assert objects[0]["attributes"]["computed_measurements"]["area_m2"] == 100
    assert objects[0]["attributes"]["source_values"][0]["measure_value"] == "00100.00"
    camera = next(row for row in objects if row["kind"] == "camera")
    assert camera["attributes"]["device_iri"] is None and camera["attributes"]["depth_m"] is None
    assert camera["attributes"]["area_memberships"][0]["area_iri"] == source["objects"][0]["iri"]
    provenance = json.loads(files["provenance.json"])
    assert len(provenance["source_files"]) == len(provenance["source_tables"]) == 1
    assert provenance["source_tables"][0]["columns"] == ["code", "geometry"]
    graph = Graph().parse(data=files["business.nt"], format="nt")
    assert (URIRef(camera["iri"]), URIRef(NS + "property:spatiallyWithinCandidate"), URIRef(objects[0]["iri"])) in graph
    assert report["counts"]["display_faces"] == 1
    for name, item in report["files"].items():
        assert hashlib.sha256((tmp_path / "public" / name).read_bytes()).hexdigest() == item["sha256"]


def test_public_export_is_reproducible_and_does_not_modify_private_input(tmp_path):
    bundle_path = write_bundle(tmp_path, candidate_bundle())
    original = bundle_path.read_bytes()
    export_public_bundle(bundle_path, tmp_path / "a")
    export_public_bundle(bundle_path, tmp_path / "b")
    assert {p.name: p.read_bytes() for p in (tmp_path / "a").iterdir()} == {p.name: p.read_bytes() for p in (tmp_path / "b").iterdir()}
    assert bundle_path.read_bytes() == original


@pytest.mark.parametrize("issue", ["dangling_relation", "private_instance", "runtime_source_path", "nested_status_payload", "bounds_payload"])
def test_public_export_rejects_unsafe_or_unresolved_identity_before_any_output(tmp_path, issue):
    bundle = candidate_bundle()
    if issue == "dangling_relation": bundle["relations"][0]["object"] = NS + "instance:missing"
    elif issue == "private_instance": bundle["objects"][0]["iri"] = NS + "source:private"
    elif issue == "runtime_source_path": bundle["source_files"][0]["path"] = "C:/PRIVATE-RUNTIME/input.json"
    elif issue == "nested_status_payload": bundle["relations"][0]["status"] = {"payload": PRIVATE}
    else: bundle["map"]["bounds"] = {"payload": PRIVATE}
    with pytest.raises(ValueError):
        export_public_bundle(write_bundle(tmp_path, bundle), tmp_path / "public")
    assert not (tmp_path / "public").exists()


def test_export_refuses_to_mix_reviewed_outputs_with_existing_private_files(tmp_path):
    output = tmp_path / "public"
    output.mkdir()
    (output / "private-bundle.json").write_text(PRIVATE, encoding="utf-8")
    with pytest.raises(ValueError, match="unreviewed"):
        export_public_bundle(write_bundle(tmp_path, candidate_bundle()), output)
    assert [path.name for path in output.iterdir()] == ["private-bundle.json"]
    assert (output / "private-bundle.json").read_text(encoding="utf-8") == PRIVATE
