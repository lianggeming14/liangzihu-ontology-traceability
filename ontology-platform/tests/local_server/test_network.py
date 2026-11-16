"""Literal navigation fixtures: record identity is distinct from RDF identity."""
import gzip
import importlib.util
import json

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS, OWL

A, B = "urn:test:class:A", "urn:test:class:B"
P = "urn:test:relation:feeds"
ONE, TWO, THREE = ("urn:test:instance:" + v for v in ("one", "two", "three"))


def save(root, relative, value):
    path = root / "data" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False).encode()
    path.write_bytes(gzip.compress(payload, mtime=0) if relative.endswith(".gz") else payload)


def navigation(root, *, sharded=False, second=False):
    edge = {"iri": P, "edge_iri": "urn:test:edge:1", "target_iri": TWO,
            "target_class_iri": B, "resolution": "resolved", "label": "feeds",
            "source_record_iri": "urn:test:source:PRIVATE", "raw_payload": "PRIVATE"}
    missing = {"iri": P, "edge_iri": "urn:test:edge:missing", "target_id": "absent",
               "target_class_iri": B, "resolution": "unresolved", "reason": "missing target"}
    one = {"iri": ONE, "label": "One", "class_iri": A, "outgoing": [edge, {**edge, "edge_iri": "urn:test:edge:2"}, edge],
           "incoming": [], "unresolved_relations": [missing], "provenance": {"source_record_iri": "PRIVATE"}}
    two = {"iri": TWO, "label": "Two", "class_iri": B, "outgoing": [], "incoming": [{**edge, "source_iri": ONE}], "unresolved_relations": []}
    others = [two]
    if second:
        one["outgoing"].append({**edge, "edge_iri": "urn:test:edge:3", "target_iri": THREE})
        others.append({**two, "iri": THREE, "label": "Three", "incoming": []})
    manifest = {"namespace": "urn:test:", "concepts": [
        {"iri": A, "label": "Class A", "parent_iri": None, "instance_count": 1, "total_instance_count": 1, "role": "source", "instances_path": "classes/a.json.gz"},
        {"iri": B, "label": "Class B", "parent_iri": A, "instance_count": len(others), "total_instance_count": len(others), "role": "source", "instances_path": "classes/b.json.gz"}]}
    if sharded:
        relative = "relations/a/one/outgoing-00001.json.gz"
        save(root, relative, {"contract": "fish-rdf-relations/1", "instance_iri": ONE, "direction": "outgoing", "edges": one["outgoing"]})
        one["outgoing_count"] = len(one["outgoing"])
        one.update(outgoing=[], outgoing_pages=[relative], detail_path="details/a/00001.json.gz")
        save(root, one["detail_path"], {"class_iri": A, "instances": [one]})
        summary = {k: one[k] for k in ("iri", "label", "class_iri", "detail_path")}
    else:
        summary = one
    save(root, "classes/a.json.gz", {"class_iri": A, "instances": [summary]})
    save(root, "classes/b.json.gz", {"class_iri": B, "instances": others})
    return manifest


def test_network_builder_exists():
    assert importlib.util.find_spec("local_server.network") is not None, "Network builder must exist"


@pytest.mark.parametrize("sharded", [False, True])
def test_records_and_triples_are_deduplicated_without_incoming_or_private_payload(tmp_path, sharded):
    from local_server.network import build_network
    network = build_network(tmp_path, navigation(tmp_path, sharded=sharded))
    assert network["contract"] == "lzo-ontology-network/1"
    assert {n["iri"] for n in network["nodes"]} == {A, B}
    assert len(network["edges"]) == 1
    edge = network["edges"][0]
    assert (edge["source"], edge["predicate"], edge["target"], edge["count"], edge["direction"]) == (A, P, B, 1, "outgoing")
    assert edge["unique_record_count"] == 2
    assert network["counts"]["unique_record_count"] == 3
    assert network["counts"]["unique_triple_count"] == 1
    assert network["counts"]["unresolved_count"] == 1
    assert "PRIVATE" not in json.dumps(network)
    assert "source_record_iri" not in json.dumps(network)


def test_schema_edges_require_actual_class_and_object_property_statements(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    graph = Graph()
    graph.add((URIRef(B), RDFS.subClassOf, URIRef(A)))
    object_property = URIRef("urn:test:relation:owns")
    literal_property = URIRef("urn:test:property:name")
    for prop, kind in [(object_property, OWL.ObjectProperty), (literal_property, OWL.DatatypeProperty)]:
        graph.add((prop, RDF.type, kind))
        graph.add((prop, RDFS.domain, URIRef(A)))
        graph.add((prop, RDFS.range, URIRef(B)))
    graph.add((URIRef(A), RDFS.subClassOf, URIRef("urn:outside:class:Unknown")))
    network = build_network(tmp_path, manifest, schema_graph=graph)
    edges = [e for e in network["edges"] if e["kind"] == "schema"]
    assert {(e["source"], e["predicate"], e["target"]) for e in edges} == {(B, str(RDFS.subClassOf), A), (A, str(object_property), B)}


def test_private_and_unknown_targets_are_never_network_nodes(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    path = tmp_path / "data/classes/a.json.gz"
    value = json.loads(gzip.decompress(path.read_bytes()))
    value["instances"][0]["outgoing"] += [
        {"iri": P, "edge_iri": "e4", "target_iri": "urn:test:instance:missing", "resolution": "resolved"},
        {"iri": "http://www.w3.org/ns/prov#wasDerivedFrom", "edge_iri": "e5", "target_iri": "urn:test:source:PRIVATE", "resolution": "resolved"}]
    save(tmp_path, "classes/a.json.gz", value)
    result = build_network(tmp_path, manifest)
    assert result["counts"]["unique_triple_count"] == 1
    assert result["counts"]["unresolved_count"] == 2
    assert result["counts"]["excluded_private_count"] == 1


def test_navigation_paths_cannot_escape_data_root(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    manifest["concepts"][0]["instances_path"] = "../private.json"
    with pytest.raises(ValueError):
        build_network(tmp_path, manifest)


def test_write_network_emits_only_paginated_public_relation_endpoints(tmp_path):
    from local_server.network import write_network
    result = write_network(tmp_path, navigation(tmp_path, sharded=True, second=True))
    saved = json.loads((tmp_path / "data/ontology-network.json").read_text(encoding="utf8"))
    assert saved == result
    edge = result["edges"][0]
    index = result["relation_index"][edge["id"]]
    assert index["count"] == 2
    page = json.loads((tmp_path / index["pages"][0]["path"]).read_text(encoding="utf8"))
    assert {(r["source_iri"], r["predicate"], r["target_iri"], r["record_count"]) for r in page["items"]} == {(ONE, P, TWO, 2), (ONE, P, THREE, 1)}
    assert "PRIVATE" not in json.dumps(page)
    assert "edge_iri" not in json.dumps(page)


def test_legacy_demo_relations_use_relation_iri_and_only_canonical_direction(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    path = tmp_path / "data/classes/a.json.gz"
    value = json.loads(gzip.decompress(path.read_bytes()))
    row = value["instances"][0]
    demo = {"assignment_iri": "urn:test:assignment:one", "relation_iri": "urn:test:demo:assignedTo",
            "target_iri": TWO, "target_class_iri": B, "direction": "outgoing", "synthetic": True}
    row["demo_assignments"] = [demo, {**demo, "direction": "incoming"}]
    save(tmp_path, "classes/a.json.gz", value)
    result = build_network(tmp_path, manifest)
    assert result["counts"]["unique_record_count"] == 4
    assert result["counts"]["unique_triple_count"] == 2
    assert result["counts"]["canonical_record_count"] == 3
    assert result["counts"]["demo_assignment_record_count"] == 1
    assert result["demo_assignments_nature"] == "synthetic"
    assert {e["predicate"] for e in result["edges"]} == {P, "urn:test:demo:assignedTo"}


def test_relation_shards_cannot_change_owner_or_direction(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path, sharded=True)
    path = tmp_path / "data/relations/a/one/outgoing-00001.json.gz"
    value = json.loads(gzip.decompress(path.read_bytes()))
    value.update(instance_iri=TWO, direction="incoming")
    save(tmp_path, "relations/a/one/outgoing-00001.json.gz", value)
    with pytest.raises(ValueError):
        build_network(tmp_path, manifest)


def test_declared_outgoing_count_cannot_silently_drop_relationships(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path, sharded=True)
    path = tmp_path / "data/details/a/00001.json.gz"
    value = json.loads(gzip.decompress(path.read_bytes()))
    value["instances"][0]["outgoing_count"] = 50
    save(tmp_path, "details/a/00001.json.gz", value)
    with pytest.raises(ValueError):
        build_network(tmp_path, manifest)


def test_missing_detail_instance_cannot_silently_clip_published_network(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path, sharded=True)
    save(tmp_path, "details/a/00001.json.gz", {"class_iri": A, "instances": []})
    with pytest.raises(ValueError):
        build_network(tmp_path, manifest)


@pytest.mark.parametrize("remaining", [0, 1])
def test_class_index_cannot_omit_declared_direct_members(tmp_path, remaining):
    from local_server.network import build_network
    manifest = navigation(tmp_path, second=True)
    path = tmp_path / "data/classes/b.json.gz"
    value = json.loads(gzip.decompress(path.read_bytes()))
    value["instances"] = value["instances"][:remaining]
    save(tmp_path, "classes/b.json.gz", value)
    with pytest.raises(ValueError):
        build_network(tmp_path, manifest)


def test_positive_direct_instance_count_requires_class_index_path(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    manifest["concepts"][0]["instances_path"] = None
    with pytest.raises(ValueError):
        build_network(tmp_path, manifest)


def test_zero_direct_ancestor_does_not_require_its_own_instance_index(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    ancestor = "urn:test:class:Ancestor"
    manifest["concepts"].append({"iri": ancestor, "label": "Ancestor", "instance_count": 0,
                                 "total_instance_count": 2, "instances_path": None})
    manifest["concepts"][0]["parent_iri"] = ancestor
    network = build_network(tmp_path, manifest)
    node = next(row for row in network["nodes"] if row["iri"] == ancestor)
    assert node["instance_count"] == 0
    assert node["total_instance_count"] == 2
    assert network["counts"]["instances"] == 2


def test_public_class_index_cannot_silently_drop_private_members(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    save(tmp_path, "classes/a.json.gz", {"class_iri": A, "instances": [{"iri": "urn:test:source:PRIVATE", "class_iri": A}]})
    with pytest.raises(ValueError):
        build_network(tmp_path, manifest)


def test_excluded_private_classes_have_explicit_counts_without_exposing_identifiers(tmp_path):
    from local_server.network import build_network
    manifest = navigation(tmp_path)
    manifest["concepts"].append({"iri": "urn:test:class:SourceRecord", "label": "PRIVATE", "instance_count": 3,
                                 "total_instance_count": 3, "instances_path": None})
    network = build_network(tmp_path, manifest)
    assert network["counts"]["excluded_private_class_count"] == 1
    assert network["counts"]["excluded_private_instance_count"] == 3
    assert "PRIVATE" not in json.dumps(network)
    assert "SourceRecord" not in json.dumps(network)
