"""Multidimensional current-network tests on a real isolated SQLite file.

These prove prototype graph behavior, not PostgreSQL integration.
"""
from pathlib import Path
from uuid import uuid4
import pytest
from agri.network import build_network
from agri.service import DomainError, Service
from agri.sqlite_db import SQLiteDatabase
from agri.seed import seed_demo


@pytest.fixture()
def network_data(tmp_path):
    db = SQLiteDatabase("sqlite:///" + str(tmp_path / "network.db"))
    db.migrate()
    service = Service(db)
    ids = seed_demo(service, tmp_path)
    actor = {"id":"network-reader","tenant_id":"demo-farm","roles":["reader"]}
    return service, ids, actor


def closed(result):
    keys = {node["id"] for node in result["nodes"]}
    assert all(edge["source"] in keys and edge["target"] in keys for edge in result["edges"])


def test_real_multidimensional_records_are_joined_without_semantic_collapse(network_data):
    service, ids, actor = network_data
    result = build_network(service, "demo-farm", actor, {"limit":300})
    assert {"space","production","material","event","evidence","observation","assertion"} <= {
        edge["dimension"] for edge in result["edges"]}
    assert any(node["kind"]=="event" for node in result["nodes"])
    assert any(node["kind"]=="evidence" for node in result["nodes"])
    assert result["view"]["kind"] == "current"
    assert result["view"]["historical_slice_supported"] is False
    closed(result)


def test_entity_identity_and_virtual_identifiers_are_distinct(network_data):
    service, ids, actor = network_data
    result = build_network(service, "demo-farm", actor, {"limit":300})
    field = next(node for node in result["nodes"] if node["id"]==ids["field"])
    assert field["entity_key"] == ids["field"]
    assert field["entity_type"] == "field"
    assert field["name"]
    for node in result["nodes"]:
        if node["kind"] in {"event","evidence","observation","assertion","relation"}:
            assert node["id"].startswith(node["kind"]+":")
            assert "entity_key" not in node
            assert node["name"]


def test_relation_evidence_targets_reified_relation_not_its_subject(network_data):
    service, ids, actor = network_data
    result = build_network(service, "demo-farm", actor, {"limit":300})
    by_id = {node["id"]:node for node in result["nodes"]}
    evidence_edges = [edge for edge in result["edges"]
                      if edge["source"]=="evidence:"+ids["evidence"] and edge["target"].startswith("relation:")]
    assert evidence_edges
    for edge in evidence_edges:
        assert edge["predicate"] == "source_record_for"
        assert edge["qualifiers"]["meaning"] == "provenance_link_not_truth_assessment"
        assert by_id[edge["target"]]["kind"] == "relation"
    spatial = [edge for edge in result["edges"] if edge["predicate"]=="core:locatedIn"]
    assert spatial and all(edge["relation_ref"] in by_id for edge in spatial)


def test_material_edges_come_only_from_material_ancestry(network_data):
    service, ids, actor = network_data
    result = build_network(service, "demo-farm", actor, {"limit":300})
    material = [edge for edge in result["edges"] if edge["dimension"]=="material"]
    actual = {(edge["source"],edge["target"]) for edge in material}
    assert (ids["paddy"],ids["rice"]) in actual
    assert (ids["rice"],ids["rice_a"]) in actual
    assert (ids["package"],ids["rice_a"]) not in actual
    assert (ids["crayfish"],ids["rice_a"]) not in actual
    assert all(edge["predicate"]=="materialAncestorOf" for edge in material)
    assert any(edge["dimension"]=="event" and edge.get("role")=="contained_item"
               for edge in result["edges"])


def test_dimension_filter_keeps_endpoints_closed(network_data):
    service, _, actor = network_data
    result = build_network(service,"demo-farm",actor,{"dimension":"space","limit":300})
    assert result["edges"]
    assert all(edge["dimension"]=="space" for edge in result["edges"])
    closed(result)


def test_center_depth_one_is_a_bounded_neighborhood(network_data):
    service, ids, actor = network_data
    result = build_network(service,"demo-farm",actor,{"center":ids["field"],"depth":1,"limit":300})
    assert ids["field"] in {node["id"] for node in result["nodes"]}
    for node in result["nodes"]:
        if node["id"] != ids["field"]:
            assert any({edge["source"],edge["target"]} == {ids["field"],node["id"]}
                       for edge in result["edges"])
    assert result["truncated"] is True
    assert any(gap.startswith("depth_limit") for gap in result["gaps"])
    closed(result)


def test_small_node_budget_marks_truncation(network_data):
    service, _, actor = network_data
    result = build_network(service,"demo-farm",actor,{"limit":2})
    assert len(result["nodes"]) <= 2
    assert result["truncated"] is True
    assert any(gap.startswith("node_limit") for gap in result["gaps"])
    closed(result)


def test_stored_graph_labels_ended_relations_without_promoting_candidates(network_data):
    service, _, actor = network_data
    with service.db.transaction() as tx:
        existing = tx.execute('SELECT id FROM relations WHERE tenant_id=%s ORDER BY id LIMIT 2',('demo-farm',)).fetchall()
        assert len(existing) == 2
        tx.execute('UPDATE relations SET valid_from=%s,valid_to=%s WHERE tenant_id=%s AND id=%s',
                   ('2020-01-01T00:00:00Z','2021-01-01T00:00:00Z','demo-farm',existing[0]['id']))
        tx.execute('UPDATE relations SET valid_from=%s,valid_to=NULL,status=%s WHERE tenant_id=%s AND id=%s',
                   ('2020-01-01T00:00:00Z','candidate','demo-farm',existing[1]['id']))
    graph = build_network(service,'demo-farm',actor,{'limit':300})
    by_id = {e['record_id']:e for e in graph['edges'] if e['id'].startswith('relation-edge:')}
    assert by_id[existing[0]['id']]['temporal_status'] == 'ended'
    assert by_id[existing[0]['id']]['within_valid_interval'] is False
    assert by_id[existing[1]['id']]['temporal_status'] == 'active'
    assert by_id[existing[1]['id']]['status'] == 'candidate'
    assert graph['view']['relation_membership'] == 'stored_records_including_candidates_and_ended_intervals'


def test_other_tenant_and_center_are_not_visible(network_data):
    service, _, actor = network_data
    other = service.mutate("create_entity","other-tenant",
        {"id":"other-admin","tenant_id":"other-tenant","roles":["admin"]},
        {"entity_type":"field","name":"PRIVATE OTHER TENANT"}, "other-private")
    result = build_network(service,"demo-farm",actor,{"limit":300})
    assert other["entity_key"] not in {node["id"] for node in result["nodes"]}
    assert all("PRIVATE" not in node["name"] for node in result["nodes"])
    with pytest.raises(DomainError) as error:
        build_network(service,"demo-farm",actor,{"center":other["entity_key"]})
    assert error.value.status == 404
    with pytest.raises(DomainError) as error:
        build_network(service,"other-tenant",actor,{})
    assert error.value.status == 403


def test_read_authorization_precedes_graph_access(network_data):
    service, _, _ = network_data
    with pytest.raises(DomainError) as error:
        build_network(service,"demo-farm",{"id":"no-access","roles":[]},{})
    assert error.value.status == 403


@pytest.mark.parametrize("params", [
    {"valid_at":"2026-01-01T00:00:00Z"},{"known_at":"2026-01-01T00:00:00Z"},
    {"revision":"1"},{"depth":0},{"depth":6},{"limit":0},{"limit":301},
    {"center":"not-a-uuid"},
])
def test_unsupported_slices_and_invalid_budgets_fail_explicitly(network_data, params):
    service, _, actor = network_data
    with pytest.raises(DomainError) as error:
        build_network(service,"demo-farm",actor,params)
    assert error.value.status == 422


def test_candidate_assertion_is_not_promoted_to_an_ordinary_fact_edge(network_data):
    service, ids, actor = network_data
    claim = service.mutate("create_assertion","demo-farm",
        {"id":"reporter","tenant_id":"demo-farm","roles":["operator"]},
        {"subject_key":ids["field"],"predicate_id":"candidate:potentialCause",
         "value":{"text":"synthetic hypothesis"},"origin":"model","evidence_ids":[ids["evidence"]]},
        "candidate-network-test")
    result = build_network(service,"demo-farm",actor,{"limit":300})
    node = next(node for node in result["nodes"] if node["id"]=="assertion:"+claim["id"])
    assert node["status"]=="candidate"
    assert not any(edge["source"]==ids["field"] and edge["predicate"]=="candidate:potentialCause"
                   for edge in result["edges"])
    assert any(edge["source"]==node["id"] and edge["target"]==ids["field"]
               and edge["status"]=="candidate" for edge in result["edges"])


def test_loading_window_is_bounded_and_reports_omitted_candidates(network_data):
    service, _, actor = network_data
    admin = {"id":"bulk-seeder","tenant_id":"demo-farm","roles":["admin"]}
    for index in range(65):
        service.mutate("create_entity","demo-farm",admin,
                       {"entity_type":"field","name":"Synthetic bounded graph "+str(index)},
                       "network-window:"+str(index))
    result = build_network(service,"demo-farm",actor,{"limit":2})
    assert any(gap.startswith("loading_limit") for gap in result["gaps"])
    assert result["truncated"] is True
    cap = result["query"]["row_budget_per_table"]
    assert all(count <= cap * 2 for count in result["counts"]["source_rows_loaded"].values())
    assert len(result["nodes"]) <= 2
    closed(result)


def test_large_qualifier_payload_is_not_loaded_into_graph_response(network_data):
    service, ids, actor = network_data
    relation = service.mutate("create_relation","demo-farm",
        {"id":"bounded-admin","tenant_id":"demo-farm","roles":["admin"]},
        {"subject_key":ids["system"],"object_key":ids["field"],
         "package_id":"agri.core","package_version":"1.0.0","predicate_id":"core:locatedIn",
         "valid_from":"2026-10-01T00:00:00+08:00","status":"accepted",
         "evidence_ids":[ids["evidence"]],"qualifiers":{"large_note":"x"*12000}},
        "network-large-qualifiers")
    result = build_network(service,"demo-farm",actor,{"limit":300})
    assert result["truncated"] is True
    assert any(gap.startswith("field_loading_limit:qualifiers") for gap in result["gaps"])
    direct = next(edge for edge in result["edges"] if edge["id"]=="relation-edge:"+relation["id"])
    assert direct["qualifiers"] == {}
    assert result["query"]["json_field_character_limit"] == 8192
    closed(result)
