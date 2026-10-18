"""Reviewed source artifacts, bounded import planning and real service integration.

All instance values in this test module are synthetic. PostgreSQL runs use the
shared isolated-schema fixture; SQLite must not be reported as a PostgreSQL pass.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest

from integrations.liangzihu import (DIRECTORY, EXPORT, canonical_bytes, canonical_key, load_bundle, load_profile,
                                    make_batch, plan_batches, read_records, strict_json)
from ops.import_liangzihu import ApiClient, apply_plan, load_plan, save_plan

ROOT = Path(__file__).resolve().parents[2]
ACTOR = {"id": "synthetic-adapter-test", "roles": ["admin"], "tenant_id": "adapter-test"}
WHEN = "2026-10-18T08:00:00Z"


def fixture_records():
    return read_records(DIRECTORY / "synthetic-core-example.json")[0]


def profile_for_graph():
    return {"source_id": "synthetic-graph", "profile_id": "synthetic-graph", "version": "1.0.0", "tables": [
        {"table": "nodes", "primary_key": ["id"], "key_types": {"id": "string"}, "fields": [],
         "relations": [{"relation_key": "parent", "fields": ["parent_id"], "target_table": "nodes", "target_fields": ["id"], "nullable": True}],
         "deferred_fields": [], "rejected_fields": []}]}


def test_generated_artifacts_match_accepted_workbook_and_all_source_columns():
    spec = importlib.util.spec_from_file_location("build_source_profile", ROOT / "tools/ontology_export/build_source_profile.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    catalog = json.loads((EXPORT / "schema_catalog.json").read_text(encoding="utf-8"))
    workbook = json.loads((EXPORT / "workbook_data.json").read_text(encoding="utf-8"))
    profile, coverage = builder.build_profile(catalog, workbook)
    assert profile == load_profile("liangzihu-platform")
    assert coverage == json.loads((DIRECTORY / "coverage-manifest.json").read_text(encoding="utf-8"))
    assert coverage["counts"]["mapped_tables"] == 122
    assert coverage["counts"]["mapped_properties"] == 979
    assert coverage["counts"]["mapped_relations"] == 409
    assert len({(item["table"], item["field"]) for item in coverage["fields"]}) == 2114
    assert len({(item["table"], item["constraint"]) for item in coverage["relations"]}) == 555
    assert len(coverage["tables"]) == 190
    assert builder.export_sql(profile, catalog) == (DIRECTORY / "readonly-export.sql").read_text(encoding="utf-8")
    assert len(load_bundle("synthetic-source")["packages"]) == 18


def test_whitelist_export_never_selects_secret_or_deferred_payloads():
    sql = (DIRECTORY / "readonly-export.sql").read_text(encoding="utf-8")
    assert "SELECT *" not in sql.upper()
    assert '"password_hash"' not in sql
    assert '"wecom_identity_evidence"' not in sql
    assert '"boundary" AS "boundary"' not in sql
    assert '"value"::text AS "value"' in sql  # Decimal precision survives JSON.
    assert "REPEATABLE READ READ ONLY" in sql
    assert "AT TIME ZONE 'UTC'" in sql
    tables = {item["table"]: item for item in load_profile("test")["tables"]}
    assert "password_hash" in tables["users"]["rejected_fields"]
    assert {x["field"] for x in tables["objects"]["deferred_fields"]} == {"boundary"}


def test_source_key_canonicalization_matches_backend_and_does_not_reuse_entity_id():
    from agri.source_mapping import _key
    table = {"table": "multi", "primary_key": ["id", "path"], "key_types": {"id": "uuid", "path": "string"}}
    values = {"id": "A0000000000040008000000000000001", "path": " a/b "}
    assert canonical_key(table, values) == _key(table, values)
    integer = {"table": "ints", "primary_key": ["id"], "key_types": {"id": "integer"}}
    for value in (1, "9007199254740992", "-0"):
        assert canonical_key(integer, {"id": value}) == _key(integer, {"id": value})
    with pytest.raises(ValueError):
        canonical_key(integer, {"id": 9007199254740992})


def test_large_chain_is_planned_parent_first_without_recursive_stack():
    records = [{"table": "nodes", "values": {"id": str(i), "parent_id": str(i - 1) if i else None}} for i in reversed(range(1500))]
    plan = plan_batches(profile_for_graph(), records, WHEN, data_nature="synthetic")
    assert plan["batch_count"] == 15
    seen = set()
    for batch in plan["batches"]:
        assert len(batch["records"]) <= 100
        current = {row["values"]["id"] for row in batch["records"]}
        for row in batch["records"]:
            parent = row["values"]["parent_id"]
            assert parent is None or parent in seen or parent in current
        seen |= current
        assert batch["data_nature"] == "synthetic"
    assert len(seen) == 1500


def test_scc_cycle_is_one_batch_or_fails_when_larger_than_budget():
    records = [{"table": "nodes", "values": {"id": str(i), "parent_id": str((i + 1) % 7)}} for i in range(7)]
    plan = plan_batches(profile_for_graph(), records, WHEN, batch_size=7)
    assert plan["batch_count"] == 1
    with pytest.raises(ValueError, match="cycle exceeds"):
        plan_batches(profile_for_graph(), records, WHEN, batch_size=6)


def test_missing_fk_and_duplicate_identity_fail_before_producing_batches():
    row = {"table": "nodes", "values": {"id": "child", "parent_id": "missing"}}
    with pytest.raises(ValueError, match="unresolved foreign key"):
        plan_batches(profile_for_graph(), [row], WHEN)
    known = [{"source_id": "synthetic-graph", "source_table": "nodes", "source_key": {"id": "missing"}, "revision": 3}]
    assert plan_batches(profile_for_graph(), [row], WHEN, existing_bindings=known)["batch_count"] == 1
    with pytest.raises(ValueError, match="Duplicate source identity"):
        plan_batches(profile_for_graph(), [row, row], WHEN, existing_bindings=known)


def test_plan_adds_optimistic_revision_and_preserves_explicit_zero():
    row = {"table": "nodes", "values": {"id": "same"}}
    binding = [{"source_id": "synthetic-graph", "table": "nodes", "source_key": {"id": "same"}, "revision": 4}]
    planned = plan_batches(profile_for_graph(), [row], WHEN, existing_bindings=binding)
    assert planned["batches"][0]["records"][0]["expected_revision"] == 4
    row["expected_revision"] = 0
    planned = plan_batches(profile_for_graph(), [row], WHEN, existing_bindings=binding)
    assert planned["batches"][0]["records"][0]["expected_revision"] == 0


def test_planner_rejects_security_fields_and_unknown_columns():
    profile = load_profile("synthetic-source")
    row = {"table": "users", "values": {"id": "00000000-0000-4000-8000-000000000001", "password_hash": "synthetic-not-a-password"}}
    with pytest.raises(ValueError, match="rejected source fields"):
        plan_batches(profile, [row], WHEN)
    row["values"].pop("password_hash")
    row["values"]["unreviewed_field"] = "x"
    with pytest.raises(ValueError, match="unmapped source fields"):
        plan_batches(profile, [row], WHEN)


def test_input_reader_rejects_duplicates_nonfinite_and_keeps_decimal_float_visible(tmp_path):
    with pytest.raises(ValueError, match="duplicate field"):
        strict_json('{"id":1,"id":2}')
    with pytest.raises(ValueError, match="Non-finite"):
        strict_json('{"value":NaN}')
    filename = tmp_path / "records.jsonl"
    filename.write_text('{"table":"nodes","values":{"id":"x","value":0.1}}\n', encoding="utf-8")
    rows, metadata = read_records(filename)
    assert isinstance(rows[0]["values"]["value"], float)
    assert metadata == {}


def test_reviewed_plan_detects_tampering_and_default_apply_plan_never_connects(tmp_path):
    profile = load_profile("synthetic-source")
    plan = plan_batches(profile, fixture_records(), WHEN, batch_size=3, data_nature="synthetic")
    save_plan(plan, tmp_path, "synthetic")
    result = apply_plan(None, tmp_path)
    assert result["read_only"] and result["remote_preflight"] == "not_run"
    path = tmp_path / "batch-00001.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="content changed"):
        load_plan(tmp_path)


def test_http_client_refuses_secret_in_url_and_cleartext_remote():
    with pytest.raises(ValueError):
        ApiClient("https://user:pass@example.test", "synthetic")
    with pytest.raises(ValueError):
        ApiClient("http://example.test", "synthetic")


def test_cli_multi_batch_stops_at_failure_and_replays_exact_payloads(tmp_path):
    plan = plan_batches(load_profile("synthetic-cli"), fixture_records(), WHEN, batch_size=3, data_nature="synthetic")
    save_plan(plan, tmp_path, "synthetic")

    class Client:
        def __init__(self):
            self.calls = []
            self.fail = True

        def request(self, route, payload, *, key=None):
            self.calls.append((route, deepcopy(payload), key))
            if self.fail and payload["batch_id"] == plan["batches"][1]["batch_id"]:
                raise ValueError("simulated network failure")
            return {"status": "stored", "batch_id": payload["batch_id"]}

    client = Client()
    with pytest.raises(ValueError, match="simulated network failure"):
        apply_plan(client, tmp_path, apply=True)
    assert len(client.calls) == 3  # First preview/apply, then the failing second preview.
    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert len(progress["completed_batches"]) == 1
    assert (tmp_path / "receipt-00001.json").exists()
    first_write = client.calls[1]
    client.fail = False
    result = apply_plan(client, tmp_path, apply=True)
    assert result["batch_count"] == 4
    assert client.calls[4] == first_write  # The original body and idempotency key are stable.


def test_full_reviewed_bundle_preview_import_duplicate_revision_and_evidence(database):
    from agri.service import DomainError
    from agri.source_mapping import SourceMappingService
    service = SourceMappingService(database)
    bundle = load_bundle("synthetic-liangzihu")
    bundle["batch"] = make_batch(bundle["profile"], fixture_records(), WHEN, "synthetic-full-1", "synthetic")
    preview = service.preview_source_bundle("adapter-test", ACTOR, bundle)
    assert preview["read_only"]
    assert service.query("entities", "adapter-test", ACTOR)["items"] == []
    result = service.mutate("install_source_bundle", "adapter-test", ACTOR, bundle, "synthetic-install")
    imported = result["batch"]
    assert imported["counts"]["created"] == 11
    repeat = service.mutate("import_source_batch", "adapter-test", ACTOR, bundle["batch"], "synthetic-repeat-new-http-key")
    assert repeat["records"] == imported["records"]
    rows = {row["source_key"]["id"]: row for row in imported["records"]}
    field_row = rows["00000000-0000-4000-8000-000000000003"]
    assert field_row["entity_key"] != field_row["source_key"]["id"]
    entity = service.query("entity", "adapter-test", ACTOR, {"entity_key": field_row["entity_key"]})
    assert entity["entity_type"] == "lzhu:objects"
    assert entity["attributes"]["lzhu:objects.kind"]["value"] == "field"
    assert entity["attributes"]["synthetic"] is True
    update = make_batch(bundle["profile"], [{"table": "objects", "expected_revision": 1,
                        "values": {"id": field_row["source_key"]["id"], "name": "合成稻田改名", "version": 2}}],
                        "2026-10-18T09:00:00Z", "synthetic-update-2", "synthetic")
    changed = service.mutate("import_source_batch", "adapter-test", ACTOR, update, "synthetic-update")
    assert changed["records"][0]["entity_key"] == field_row["entity_key"]
    assert changed["records"][0]["revision"] == 2
    stale = deepcopy(update)
    stale["batch_id"] = "synthetic-stale-3"
    stale["observed_at"] = "2026-10-18T10:00:00Z"
    stale["records"][0]["values"]["name"] = "冲突改名"
    with pytest.raises(DomainError):
        service.mutate("import_source_batch", "adapter-test", ACTOR, stale, "synthetic-stale")
    detail = service.query("source_bindings", "adapter-test", ACTOR, {"binding_id": field_row["binding_id"]})
    assert detail["items"][0]["revision"] == 2
    assert len(detail["items"][0]["history"]) == 2


def test_multi_batch_plan_can_commit_and_replay_through_service(database):
    from agri.source_mapping import SourceMappingService
    service = SourceMappingService(database)
    bundle = load_bundle("synthetic-split")
    plan = plan_batches(bundle["profile"], fixture_records(), WHEN, batch_size=3, data_nature="synthetic")
    service.mutate("install_source_bundle", "adapter-test", ACTOR, bundle, "install-split")
    results = []
    for batch in plan["batches"]:
        service.preview_source_batch("adapter-test", ACTOR, batch)
        results.append(service.mutate("import_source_batch", "adapter-test", ACTOR, batch, batch["batch_id"]))
    assert sum(result["counts"]["created"] for result in results) == 11
    for batch in plan["batches"]:
        # The same request, including its original expected_revision=0, is replayable.
        service.preview_source_batch("adapter-test", ACTOR, batch)
        service.mutate("import_source_batch", "adapter-test", ACTOR, batch, batch["batch_id"])
    assert len(service.query("entities", "adapter-test", ACTOR)["items"]) == 11


def test_missing_foreign_key_rolls_back_definitions_and_all_records(database):
    from agri.service import DomainError
    from agri.source_mapping import SourceMappingService
    service = SourceMappingService(database)
    bundle = load_bundle("synthetic-invalid")
    record = deepcopy(fixture_records()[1])
    bundle["batch"] = make_batch(bundle["profile"], [record], WHEN, "missing-user", "synthetic")
    with pytest.raises(DomainError):
        service.mutate("install_source_bundle", "adapter-test", ACTOR, bundle, "must-rollback")
    assert service.query("packages", "adapter-test", ACTOR)["items"] == []
    assert service.query("entities", "adapter-test", ACTOR)["items"] == []


def test_composite_source_key_and_precise_source_values_use_real_definitions(database):
    from agri.service import DomainError
    from agri.source_mapping import SourceMappingService
    service = SourceMappingService(database)
    bundle = load_bundle("synthetic-composite")
    user, farm = fixture_records()[:2]
    user_id, farm_id = user["values"]["id"], farm["values"]["id"]
    scene_id = "00000000-0000-4000-8000-000000000101"
    asset_id = "00000000-0000-4000-8000-000000000102"
    budget_id = "00000000-0000-4000-8000-000000000103"
    records = [user, farm,
               {"table": "terrain_scenes", "values": {"id": scene_id, "object_id": farm_id, "created_by": user_id, "name": "合成地形"}},
               {"table": "media_assets", "values": {"id": asset_id, "object_id": farm_id, "created_by": user_id}},
               {"table": "terrain_resources", "values": {"scene_id": scene_id, "path": "tiles/001.glb", "asset_id": asset_id, "byte_length": 12}},
               {"table": "terrain_resources", "values": {"scene_id": scene_id, "path": "tiles/002.glb", "asset_id": asset_id, "byte_length": 13}},
               {"table": "budgets", "values": {"id": budget_id, "object_id": farm_id, "configured_by": user_id,
                                               "month": "2026-10-01", "limit_amount": "9007199254740992.123456789"}}]
    bundle["batch"] = make_batch(bundle["profile"], records, WHEN, "synthetic-composite", "synthetic")
    result = service.mutate("install_source_bundle", "adapter-test", ACTOR, bundle, "composite-install")["batch"]
    resources = [row for row in result["records"] if row["table"] == "terrain_resources"]
    assert len(resources) == 2 and resources[0]["entity_key"] != resources[1]["entity_key"]
    assert set(resources[0]["source_key"]) == {"scene_id", "path"}
    budget = next(row for row in result["records"] if row["table"] == "budgets")
    entity = service.query("entity", "adapter-test", ACTOR, {"entity_key": budget["entity_key"]})
    assert entity["attributes"]["lzhu:budgets.limit_amount"]["value"] == "9007199254740992.123456789"
    assert entity["attributes"]["lzhu:budgets.month"]["value"] == "2026-10-01"
    for index, invalid in enumerate(({"month": "2026-02-30"}, {"limit_amount": 0.1}), 1):
        patch = make_batch(bundle["profile"], [{"table": "budgets", "expected_revision": 1, "values": {"id": budget_id, **invalid}}],
                           "2026-10-18T10:00:00Z", "invalid-budget-" + str(index), "synthetic")
        with pytest.raises(DomainError):
            service.mutate("import_source_batch", "adapter-test", ACTOR, patch, "invalid-budget-" + str(index))
    relations = service.query("relations", "adapter-test", ACTOR, {"entity_key": resources[0]["entity_key"], "status": "candidate"})
    assert len(relations["items"]) == 2
