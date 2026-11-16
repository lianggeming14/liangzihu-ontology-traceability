"""Public query boundaries; network responses are synthetic SPARQL DTOs."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_server.query import QueryService, QueryError, encode_cursor, decode_cursor


@pytest.fixture
def release(tmp_path):
    manifest = {"namespace": "urn:test:", "root_iri": "https://w3id.org/lzo/ontology/DomainEntity",
                "concepts": [{"iri": "urn:test:class:ponds", "parent_iri": "https://w3id.org/lzo/ontology/DomainEntity", "label": "池塘"}],
                "counts": {"instances": 2}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return {"release_id": "r1", "namespace": "urn:test:", "rdf_graph": "urn:test:graph", "manifest_path": str(path), "navigation_dir": str(tmp_path)}


def service(release):
    config = SimpleNamespace(fuseki_url="http://127.0.0.1:23059/fish_l1", limits={"page_size": 1, "max_page_size": 5, "query_timeout_seconds": 1})
    return QueryService(config, release)


def test_cursor_is_bound_to_release_and_request():
    value = encode_cursor("r1", "instances:ponds", 3)
    assert decode_cursor(value, "r1", "instances:ponds") == 3
    for release_id, route in [("r2", "instances:ponds"), ("r1", "instances:fish")]:
        with pytest.raises(QueryError):
            decode_cursor(value, release_id, route)
    with pytest.raises(QueryError):
        decode_cursor("!!", "r1", "instances:ponds")


def test_source_records_cannot_be_requested_even_with_valid_iri(release):
    query = service(release)
    for iri in ("urn:test:source:ponds:1", "urn:test:raw:ponds:name", "urn:outside:instance:x", 'urn:test:instance:x> ?s ?p ?o'):
        with pytest.raises(QueryError):
            query.resource(iri)


def test_hierarchy_uses_recorded_manifest_without_full_graph_count(release):
    query = service(release)
    query.query = lambda _: pytest.fail("hierarchy must not query full RDF")
    result = query.children("https://w3id.org/lzo/ontology/DomainEntity")
    assert result["release_id"] == "r1"
    assert result["items"][0]["label"] == "池塘"


def test_resource_filters_private_predicates_and_source_links(release):
    query = service(release)
    responses = iter([
        [{"exists": {"type": "literal", "value": "1"}}],
        [{"predicate": {"value": "urn:test:property:ponds:name"}, "object": {"type": "literal", "value": "甲"}},
         {"predicate": {"value": "http://www.w3.org/ns/prov#wasDerivedFrom"}, "object": {"type": "uri", "value": "urn:test:source:ponds:1"}},
         {"predicate": {"value": "urn:test:raw:ponds:name"}, "object": {"type": "literal", "value": "PRIVATE"}}], []])
    query.query = lambda _: next(responses)
    result = query.resource("urn:test:instance:one")
    assert [row["object"]["value"] for row in result["outgoing"]] == ["甲"]
    assert "PRIVATE" not in json.dumps(result)
    assert result["provenance"]["data_nature"] is None
    assert result["provenance"]["release_data_nature"] == "imported_unverified"


def test_instances_page_does_not_accept_class_outside_manifest(release):
    query = service(release)
    with pytest.raises(QueryError):
        query.instances("urn:test:SourceRecord")
    rows = [{"instance": {"value": "urn:test:instance:one"}}, {"instance": {"value": "urn:test:instance:two"}}]
    query.query = lambda _: rows
    result = query.instances("urn:test:class:ponds", limit=1)
    assert len(result["items"]) == 1
    assert decode_cursor(result["next_cursor"], "r1", "instances:urn:test:class:ponds") == 1


def test_relative_release_paths_resolve_only_beneath_declared_data_root(release):
    config = service(release).config
    config.data_dir = Path(release["navigation_dir"])
    config.review_dir = config.data_dir
    value = {**release, "path_base": "data", "manifest_path": "manifest.json", "navigation_dir": "."}
    assert QueryService(config, value).manifest["namespace"] == "urn:test:"
    with pytest.raises((QueryError, ValueError)):
        QueryService(config, {**value, "manifest_path": "../private.env"})


def network_service(release):
    from local_server.network import write_network
    root = Path(release["navigation_dir"])
    concept = "urn:test:class:ponds"
    (root / "data/classes").mkdir(parents=True)
    manifest = json.loads(Path(release["manifest_path"]).read_text(encoding="utf8"))
    manifest["concepts"][0].update(instances_path="classes/ponds.json", instance_count=3, total_instance_count=3)
    items = [{"iri": "urn:test:instance:"+name, "class_iri": concept, "label": name, "outgoing": []} for name in ("one", "two", "three")]
    items[0]["outgoing"] = [{"iri": "urn:test:relation:feeds", "edge_iri": "edge:"+name,
                             "target_iri": "urn:test:instance:"+name, "resolution": "resolved"} for name in ("two", "three")]
    (root / "data/classes/ponds.json").write_text(json.dumps({"instances": items}), encoding="utf8")
    Path(release["manifest_path"]).write_text(json.dumps(manifest), encoding="utf8")
    write_network(root, manifest)
    return service(release)


def test_historical_release_without_network_is_explicitly_unavailable(release):
    reader = service(release)
    assert hasattr(reader, "network"), "Versioned network query is required"
    result = reader.network()
    assert result["release_id"] == "r1"
    assert result["available"] is False
    assert result["nodes"] == result["edges"] == []


def test_network_pages_are_bounded_release_bound_and_not_forgeable(release):
    reader = network_service(release)
    source = target = "urn:test:class:ponds"
    predicate = "urn:test:relation:feeds"
    result = reader.network_relations(source, predicate, target, limit=1)
    assert result["release_id"] == "r1"
    assert result["total"] == 2
    assert len(result["items"]) == 1
    following = reader.network_relations(source, predicate, target, limit=1, cursor=result["next_cursor"])
    assert len(following["items"]) == 1
    assert following["items"][0] != result["items"][0]
    assert following["next_cursor"] is None
    for cursor in (result["next_cursor"][:-2]+"ab", encode_cursor("r1", "network:"+predicate, 1)):
        with pytest.raises(QueryError):
            reader.network_relations(source, predicate, target, cursor=cursor)
    other = service({**release, "release_id": "r2"})
    with pytest.raises(QueryError):
        other.network_relations(source, predicate, target, cursor=result["next_cursor"])
    for limit in (0, 6, "bad"):
        with pytest.raises(QueryError):
            reader.network_relations(source, predicate, target, limit=limit)


def test_network_rejects_private_identifiers_and_tampered_public_shards(release):
    reader = network_service(release)
    concept, predicate = "urn:test:class:ponds", "urn:test:relation:feeds"
    for source, relation, target in (("urn:test:source:private", predicate, concept), (concept, "urn:test:raw:secret", concept), (concept, predicate, "urn:outside:class:A")):
        with pytest.raises(QueryError):
            reader.network_relations(source, relation, target)
    root = Path(release["navigation_dir"])
    network = json.loads((root / "data/ontology-network.json").read_text(encoding="utf8"))
    page = next(iter(network["relation_index"].values()))["pages"][0]
    path = root / page["path"]
    value = json.loads(path.read_text(encoding="utf8"))
    value["items"][0]["source_record_iri"] = "PRIVATE"
    path.write_text(json.dumps(value), encoding="utf8")
    with pytest.raises(QueryError):
        reader.network_relations(concept, predicate, concept)


def test_network_pagination_reads_across_real_500_relation_shard_boundary(release):
    from local_server.network import write_network
    root = Path(release["navigation_dir"])
    (root / "data/classes").mkdir(parents=True)
    concept, predicate = "urn:test:class:ponds", "urn:test:relation:feeds"
    manifest = json.loads(Path(release["manifest_path"]).read_text(encoding="utf8"))
    manifest["concepts"][0].update(instances_path="classes/ponds.json", instance_count=504, total_instance_count=504)
    rows = [{"iri": f"urn:test:instance:{i:04d}", "class_iri": concept, "label": str(i), "outgoing": []} for i in range(504)]
    rows[0]["outgoing"] = [{"iri": predicate, "edge_iri": str(i), "target_iri": row["iri"]} for i, row in enumerate(rows[1:])]
    (root / "data/classes/ponds.json").write_text(json.dumps({"instances": rows}), encoding="utf8")
    Path(release["manifest_path"]).write_text(json.dumps(manifest), encoding="utf8")
    write_network(root, manifest)
    reader = service(release)
    reader.config.limits["max_page_size"] = 500
    first = reader.network_relations(concept, predicate, concept, limit=499)
    last = reader.network_relations(concept, predicate, concept, limit=5, cursor=first["next_cursor"])
    assert first["total"] == last["total"] == 503
    assert len(first["items"]) == 499
    assert [row["target_iri"] for row in last["items"]] == ["urn:test:instance:0500", "urn:test:instance:0501", "urn:test:instance:0502", "urn:test:instance:0503"]
    assert last["next_cursor"] is None
