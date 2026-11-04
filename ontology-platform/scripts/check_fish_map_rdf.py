"""Executable map RDF/navigation regressions; never connects to a database."""
import copy
import importlib.util
from pathlib import Path
import unittest

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD


M = "urn:lzo:fish-review:map:v1:"
V = "urn:lzo:fish-review:sample:v1:"


def fixture():
    layer = {"id": "detail-test", "label": "Source drawing", "coordinate_space": "PDF_LANDSCAPE_LOCAL",
             "units": "pt", "viewBox": [0, 0, 100, 80], "axis": {"x": "right", "y": "down"},
             "crs": None, "georeferenced": False, "background_url": None}
    pond = {"id": "DRAW-POND-001", "object_iri": M + "object:DRAW-POND-001", "label": "Original pond",
            "canonical_key": "source:pond:001", "kind": "pond", "class_iri": M + "class:Pond",
            "asset_id": "detail-test", "parent_iri": M + "layer:detail-test", "data_nature": "imported_unverified",
            "coordinate_space": "PDF_LANDSCAPE_LOCAL", "coordinate_units": "pt", "crs": None,
            "georeferenced": False, "boundary_status": "confirmed_source_vector",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]},
            "source_object_iri": "urn:lzo:object:11111111-1111-4111-8111-111111111111",
            "source_evidence": [{"path": "source.json", "git_blob_sha1": "a"*40, "sha256": "b"*64,
                                 "record_pointer": "/records/0", "source_url": "https://example.com/source"}],
            "metrics": {"coordinate_area": {"value": "123456789012345678.123456789", "unit": "pt^2"},
                        "coordinate_length": {"value": 34.142, "unit": "pt"},
                        "surveyed_area_m2": None, "surveyed_perimeter_m": None, "depth_m": None, "volume_m3": None},
            "ledger_area": {"value": 4.93, "unit": None}, "documented_dimensions": [],
            "relations": [{"predicate": M + "inLayer", "object": M + "layer:detail-test"}]}
    return {"schema_version": "farm-map-objects/1", "source": {"repository": "https://github.com/No1dry/farm", "commit": "c"*40},
            "coordinate_spaces": [layer], "objects": [pond]}


class MapRDFChecks(unittest.TestCase):
    def module(self):
        self.assertTrue(Path(__file__).with_name("fish_map_rdf.py").is_file(), "Map RDF projection is not implemented")
        import fish_map_rdf
        return fish_map_rdf

    def build(self, payload=None):
        graph = Graph()
        for triple in self.module().project_map(payload or fixture()): graph.add(triple)
        return graph

    def test_shared_domain_type_and_typed_metrics_without_fake_depth(self):
        graph = self.build()
        pond = URIRef(M + "object:DRAW-POND-001")
        self.assertIn((pond, RDF.type, URIRef(M + "class:Pond")), graph)
        self.assertIn((URIRef(M + "class:Pond"), RDFS.subClassOf, URIRef("https://w3id.org/lzo/ontology/Pond")), graph)
        self.assertIn((pond, URIRef(M + "property:coordinate_area"),
                       Literal("123456789012345678.123456789", datatype=XSD.decimal, normalize=False)), graph)
        self.assertFalse(list(graph.objects(pond, URIRef(M + "property:depth_m"))))
        self.assertIn((pond, URIRef(V + "missingField"), URIRef(M + "property:depth_m")), graph)
        self.assertIn((pond, URIRef(M + "property:georeferenced"), Literal(False)), graph)

    def test_real_layer_relation_supports_both_directions(self):
        graph = self.build()
        pond, layer = URIRef(M + "object:DRAW-POND-001"), URIRef(M + "layer:detail-test")
        self.assertIn((pond, URIRef(M + "inLayer"), layer), graph)
        self.assertIn((layer, URIRef(M + "hasRepresentation"), pond), graph)
        navigation = self.module().MapNavigation()
        for triple in graph: navigation.add(*triple)
        concepts, tables = navigation.finish()
        self.assertEqual(tables["map_pond"]["instances"][0]["outgoing"][0]["target_iri"], str(layer))
        self.assertEqual(tables["map_layer"]["instances"][0]["incoming"][0]["source_iri"], str(pond))
        self.assertEqual(sum(c["instance_count"] for c in concepts), 2)

    def test_navigation_is_derived_from_rdf_and_has_source_not_business_payload(self):
        graph = self.build()
        pond = URIRef(M + "object:DRAW-POND-001")
        graph.set((pond, RDFS.label, Literal("RDF readback changed label")))
        navigation = self.module().MapNavigation()
        for triple in graph: navigation.add(*triple)
        _, tables = navigation.finish()
        item = tables["map_pond"]["instances"][0]
        self.assertEqual(item["label"], "RDF readback changed label")
        self.assertEqual(item["nature"], "imported_unverified")
        self.assertEqual(item["adoption_status"], "sample_not_formally_adopted")
        self.assertEqual(item["provenance"]["coordinate_space"], "PDF_LANDSCAPE_LOCAL")
        self.assertEqual(item["provenance"]["source_evidence"][0]["record_pointer"], "/records/0")
        self.assertNotIn("payload", item["provenance"])
        self.assertIsNone(next(p["value"] for p in item["properties"] if p["field"] == "depth_m"))

    def test_rejects_dangling_layer_synthetic_nature_and_wrong_class(self):
        for key, value in [("parent_iri", M + "layer:missing"), ("data_nature", "synthetic"),
                           ("class_iri", M + "class:Field")]:
            payload = fixture()
            payload["objects"][0][key] = value
            with self.assertRaises(ValueError): self.build(payload)

    def test_readback_rejects_missing_relationship_target(self):
        graph = self.build()
        layer = URIRef(M + "layer:detail-test")
        graph.remove((layer, RDF.type, None))
        navigation = self.module().MapNavigation()
        for triple in graph: navigation.add(*triple)
        with self.assertRaises(ValueError): navigation.finish()

    def test_projection_does_not_include_unrelated_raw_payload(self):
        payload = fixture()
        payload["objects"][0]["payload"] = {"secret_internal_raw": "not-for-map"}
        graph = self.build(payload)
        self.assertNotIn("not-for-map", graph.serialize(format="nt"))


if __name__ == "__main__":
    unittest.main()
