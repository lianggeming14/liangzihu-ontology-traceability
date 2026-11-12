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
