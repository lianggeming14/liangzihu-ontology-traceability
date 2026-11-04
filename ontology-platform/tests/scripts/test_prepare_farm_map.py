"""Source geometry, provenance and identity boundaries for the review map."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_farm_map.py"


def builder():
    assert SCRIPT.is_file(), "Source-verified farm map preparation is not implemented"
    spec = importlib.util.spec_from_file_location("prepare_farm_map", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inputs():
    manifest = {
        "coordinate_system": {"source_canvas": [100, 100], "source_image_native": [200, 200],
                              "metres_per_pixel": 3, "georeferenced": False},
        "boundary": {"points": [[0, 0], [100, 0], [100, 100], [0, 100]],
                     "precision": "screenshot_redline_approximate", "model_area_m2": 90000},
        "objects": [{"spatial_id": "SAT-POND-001", "asset_id": "full", "kind": "pond",
                     "name": "Source pond", "region": "west", "points": [[0, 0], [8, 0], [8, 8]],
                     "geometry": {"type": "Polygon", "coordinates": [[0, 0], [24, 0], [24, 24]]},
                     "entity_uuid": None, "model_area_m2": 900, "source": "Image interpretation",
                     "appearance_geometry_override": {"record_id": "REFINED-1"}}],
    }
    enrichment = {
        "native_to_reference": {"x_scale": .5, "y_scale": .5},
        "source_file": "reference/satellite.png", "source_sha256": "a" * 64,
        "records": [{"id": "REFINED-1", "parent_spatial_id": "SAT-POND-001", "kind": "pond",
                     "source_status": "observed", "appearance_only": True, "entity_uuid": None,
                     "geometry": {"type": "Polygon", "coordinates": [
                         [[2, 2], [20, 2], [20, 20], [2, 20], [2, 2]],
                         [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]]]},
                     "coordinate_units": "native_image_pixels", "boundary_status": "approximate_visual_outline",
                     "source_file": "reference/satellite.png", "source_hash": "a" * 64}],
    }
    drawings = {
        "drawings": [{"asset_id": "detail-a", "label": "Paper A", "page_size_pt": [80, 60],
                      "coordinate_system": "PDF_LANDSCAPE_LOCAL", "coordinate_units": "pt",
                      "source_file": "drawing.pdf", "source_hash": "b" * 64, "source_page": 1}],
        "records": [{"representation_id": "DRAW-A-E3", "asset_id": "detail-a", "label": "E3",
                     "kind": "field", "geometry": {"type": "Point", "coordinates": [12, 19]},
                     "boundary_status": "boundary_unknown", "link_verified": False,
                     "identity_scope": "unresolved_drawing_label", "source_file": "drawing.pdf",
                     "source_hash": "b" * 64, "source_page": 1, "source_evidence": [],
                     "area_original": None, "area_unit": None, "documented_dimensions": []}],
    }
    mapping = {"entities": [
        {"dataset": "real", "data_nature": "imported_unverified", "spatial_ids": ["SAT-POND-001"],
         "resource_id": "11111111-1111-4111-8111-111111111111", "iri": "urn:lzo:object:11111111-1111-4111-8111-111111111111",
         "source_key": {"canonical_key": "SAT-POND-001"}, "evidence_ids": []},
        {"dataset": "real", "data_nature": "imported_unverified", "spatial_ids": ["DRAW-A-E3"],
         "resource_id": "22222222-2222-4222-8222-222222222222", "iri": "urn:lzo:object:22222222-2222-4222-8222-222222222222",
         "source_key": {"canonical_key": "unresolved-label"}, "evidence_ids": []},
        {"dataset": "demo", "data_nature": "synthetic", "spatial_ids": ["SAT-POND-001"],
         "resource_id": "33333333-3333-4333-8333-333333333333", "iri": "urn:lzo:object:33333333-3333-4333-8333-333333333333"},
    ]}
    return manifest, enrichment, drawings, mapping


class FarmMapPreparationTests(unittest.TestCase):
    def test_uses_observed_refinement_preserves_holes_and_original_outline(self):
        module = builder()
        values = inputs()
        original = copy.deepcopy(values)
        objects, maps = module.build_map_data(*values)
        pond = objects["objects"][0]
        self.assertEqual(pond["geometry"]["coordinates"][0], [[1, 1], [10, 1], [10, 10], [1, 10], [1, 1]])
        self.assertEqual(pond["geometry"]["coordinates"][1], [[2, 2], [2, 3], [3, 3], [3, 2], [2, 2]])
        self.assertEqual(pond["original_geometry"]["coordinates"], [[[0, 0], [8, 0], [8, 8], [0, 0]]])
        self.assertEqual(pond["geometry_provenance"]["source_record_id"], "REFINED-1")
        self.assertEqual(values, original)
        self.assertEqual(maps["layers"][0]["viewBox"], [0, 0, 100, 100])
        self.assertIsNone(maps["crs"])
        self.assertFalse(maps["rfc7946"])

    def test_never_joins_demo_identity_or_infers_real_metrics(self):
        objects, maps = builder().build_map_data(*inputs())
        pond = objects["objects"][0]
        self.assertEqual(pond["source_object_iri"], "urn:lzo:object:11111111-1111-4111-8111-111111111111")
        self.assertEqual(pond["object_iri"], "urn:lzo:fish-review:map:v1:object:SAT-POND-001")
        self.assertEqual(pond["data_nature"], "imported_unverified")
        self.assertIsNone(pond["metrics"]["surveyed_area_m2"])
        self.assertIsNone(pond["metrics"]["depth_m"])
        self.assertIsNone(pond["metrics"]["volume_m3"])
        label = objects["objects"][1]
        self.assertEqual(label["kind"], "unresolved_label")
        self.assertEqual(label["geometry"], {"type": "Point", "coordinates": [12, 19]})
        self.assertEqual(maps["layers"][1]["coordinate_space"], "PDF_LANDSCAPE_LOCAL")
        self.assertEqual(maps["layers"][1]["units"], "pt")

    def test_rejects_sample_override_and_wrong_parent(self):
        module = builder()
        for field, value in [("source_status", "sample"), ("parent_spatial_id", "OTHER")]:
            values = inputs()
            values[1]["records"][0][field] = value
            with self.assertRaisesRegex(ValueError, "observed|parent"):
                module.build_map_data(*values)

    def test_missing_or_ambiguous_real_binding_fails_closed(self):
        module = builder()
        for mutation in ("missing", "duplicate"):
            values = inputs()
            if mutation == "missing":
                values[3]["entities"] = values[3]["entities"][1:]
            else:
                values[3]["entities"].append(copy.deepcopy(values[3]["entities"][0]))
            with self.assertRaisesRegex(ValueError, "identity"):
                module.build_map_data(*values)

    def test_tampered_source_refused_before_output_is_created(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "README.md").write_text("tampered", encoding="utf-8")
            target = root / "target"
            with self.assertRaisesRegex(ValueError, "blob|source|missing"):
                module.prepare(source, target)
            self.assertFalse(target.exists())

    def test_svg_escapes_source_text_and_retains_ring_holes(self):
        module = builder()
        values = inputs()
        values[0]["objects"][0]["name"] = '<script>alert("x")</script>'
        _, maps = module.build_map_data(*values)
        svg = module.render_svg(maps["layers"][0])
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)
        self.assertIn('fill-rule="evenodd"', svg)


if __name__ == "__main__":
    unittest.main()
