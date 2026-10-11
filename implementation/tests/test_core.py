"""Behavior and invariant tests, exercised independently on each configured backend.

Every fixture is synthetic. PostgreSQL cases skip explicitly when no dedicated
TEST_DATABASE_URL exists; passing SQLite cases never satisfies the PG gate.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import json
import uuid
import pytest

TENANT = "test-farm-a"
ACTOR = {"id": "synthetic-admin", "tenant_id": TENANT, "roles": ["admin"]}
WHEN = "2026-10-11T01:00:00+08:00"


def mutate(service, action, payload, key=None, tenant=TENANT, actor=None):
    actor = actor or {**ACTOR, "tenant_id": tenant}
    return service.mutate(action, tenant, actor, payload, key or uuid.uuid4().hex)


def error_type():
    from agri.service import DomainError
    return DomainError


def table_count(db, table):
    assert table in {"entities", "events", "outbox", "idempotency", "material_ancestry", "publications", "audit_log"}
    with db.transaction() as tx:
        return tx.execute("SELECT COUNT(*) AS total FROM " + table + " WHERE tenant_id=%s", (TENANT,)).fetchone()["total"]


def lot_state(db, key):
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM lots WHERE tenant_id=%s AND lot_key=%s", (TENANT, key)).fetchone()
    return {**row, **{k: Decimal(str(row[k])) for k in ("produced_quantity", "available_quantity", "shipped_quantity", "received_quantity")}}


def evidence(service, tenant=TENANT):
    return mutate(service, "create_evidence", {"kind": "synthetic_document", "uri": "https://private.example/evidence/secret.pdf", "content_hash": "a" * 64,
        "source_id": "synthetic-test", "public_summary": "合成测试凭证", "metadata": {"synthetic": True, "person_name": "不得公开", "secret": "PRIVATE_SENTINEL"}}, tenant=tenant)["id"]


def entity(service, kind="field", name="合成对象", **attrs):
    return mutate(service, "create_entity", {"entity_type": kind, "name": name, "attrs": {"synthetic": True, **attrs}})["entity_key"]


def lot(service, name="合成批次", unit="kg", product_type="https://test.example/product/Rice", batch=None):
    data = {"name": name, "product_type": product_type, "unit": unit, "attrs": {"synthetic": True}}
    if batch:
        data["production_batch_key"] = batch
    return mutate(service, "create_lot", data)["lot_key"]


def flow(key, quantity, unit="kg"):
    return {"lot_key": key, "quantity": str(quantity), "unit": unit}


def event(service, kind, evid, **data):
    return mutate(service, "create_event", {"event_type": kind, "occurred_at": WHEN, "evidence_ids": [evid], **data})


@pytest.fixture()
def harvested(service):
    evid = evidence(service)
    batch = entity(service, "production_batch", "合成生产季")
    source = lot(service, "合成原料批", batch=batch)
    created = event(service, "harvest", evid, participants=[{"entity_key": batch, "role": "production_origin"}], outputs=[flow(source, "100")])
    return {"evidence": evid, "batch": batch, "lot": source, "event": created["id"]}


def test_names_do_not_determine_identity(service, database):
    first = entity(service, name="同名合成田块")
    second = entity(service, name="同名合成田块")
    assert first != second
    assert table_count(database, "entities") == 2
    assert service.query("entity", TENANT, ACTOR, {"entity_key": first})["entity_key"] == first


def test_package_extensions_preserve_identity_for_three_domains(service, database):
    for domain in ("rice", "vegetable", "fish"):
        namespace = "https://test.example/" + domain + "/"
        package = {"package_id": "test." + domain, "version": "1.0.0", "namespace": namespace,
                   "types": [{"type_id": namespace + "ProductionBatch", "identity_type": "production_batch", "label": "合成领域生产批次"}], "predicates": [], "dependencies": []}
        mutate(service, "register_package", package)
        obj = entity(service, "production_batch", "合成" + domain)
        mutate(service, "assign_type", {"entity_key": obj, "type_id": namespace + "ProductionBatch", "package_id": "test." + domain, "version": "1.0.0"})
        actual = service.query("entity", TENANT, ACTOR, {"entity_key": obj})
        assert actual["entity_key"] == obj
        assert actual["entity_type"] == "production_batch"
    assert table_count(database, "entities") == 3


def test_actor_cannot_claim_another_tenant(service):
    with pytest.raises(error_type()) as caught:
        service.query("entities", "test-farm-b", ACTOR, {})
    assert caught.value.status == 403


def test_viewer_cannot_write_or_review(service):
    viewer = {"id": "synthetic-viewer", "roles": ["viewer"], "tenant_id": TENANT}
    with pytest.raises(error_type()) as caught:
        mutate(service, "create_entity", {"entity_type": "field", "name": "合成"}, actor=viewer)
    assert caught.value.status == 403


def test_cross_tenant_entity_and_evidence_are_not_readable(service):
    obj = entity(service)
    with pytest.raises(error_type()) as caught:
        service.query("entity", "test-farm-b", {**ACTOR, "tenant_id": "test-farm-b"}, {"entity_key": obj})
    assert caught.value.status in (403, 404)
    foreign = evidence(service, "test-farm-b")
    with pytest.raises(error_type()):
        mutate(service, "create_observation", {"subject_key": obj, "property_id": "soil.ph", "value": {"value": "6.8", "unit": "1"},
            "observed_at": WHEN, "method": "synthetic_lab", "evidence_ids": [foreign], "origin": "measured"})


def test_observation_retains_measurement_origin_and_evidence(service):
    obj, evid = entity(service), evidence(service)
    observed = mutate(service, "create_observation", {"subject_key": obj, "property_id": "soil.ph", "value": {"value": "6.80", "unit": "1"},
        "observed_at": WHEN, "method": "synthetic_lab", "evidence_ids": [evid], "origin": "reported"})
    assert observed["id"]
    bundle = service.query("evidence_bundle", TENANT, ACTOR, {"entity_key": obj})
    encoded = json.dumps(bundle, ensure_ascii=False, default=str)
    assert observed["id"] in encoded and evid in encoded and "reported" in encoded


def test_relation_endpoint_types_and_time_range_are_checked(service):
    ns = "https://test.example/core/"
    mutate(service, "register_package", {"package_id": "test.core", "version": "1.0.0", "namespace": ns,
        "types": [{"type_id": ns + "Field", "identity_type": "field", "label": "田块"}],
        "predicates": [{"predicate_id": ns + "cultivatedAt", "subject_types": ["production_batch"], "object_types": ["field"], "dimension": "production"}]})
    field, batch, evid = entity(service), entity(service, "production_batch"), evidence(service)
    payload = {"subject_key": batch, "object_key": field, "package_id": "test.core", "package_version": "1.0.0", "predicate_id": ns + "cultivatedAt",
               "valid_from": WHEN, "evidence_ids": [evid], "status": "accepted"}
    created = mutate(service, "create_relation", payload)
    assert created["id"]
    with pytest.raises(error_type()):
        mutate(service, "create_relation", {**payload, "subject_key": field})
    with pytest.raises(error_type()):
        mutate(service, "create_relation", {**payload, "valid_to": "2026-10-01T00:00:00Z"})


def test_idempotent_replay_does_not_repeat_any_writes(service, database):
    payload = {"entity_type": "field", "name": "合成幂等田块"}
    first = mutate(service, "create_entity", payload, key="create-one")
    counts = {t: table_count(database, t) for t in ("entities", "outbox", "audit_log")}
    second = mutate(service, "create_entity", deepcopy(payload), key="create-one")
    assert first == second
    assert counts == {t: table_count(database, t) for t in counts}
    with pytest.raises(error_type()) as caught:
        mutate(service, "create_entity", {**payload, "name": "不同请求"}, key="create-one")
    assert caught.value.status == 409


def test_transformation_balance_and_explicit_loss(service, database, harvested):
    a, b = lot(service, "合成甲"), lot(service, "合成乙")
    event(service, "transform", harvested["evidence"], inputs=[flow(harvested["lot"], "100")], outputs=[flow(a, "40"), flow(b, "50")], loss_quantity="10", loss_unit="kg")
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("0")
    assert lot_state(database, a)["available_quantity"] == Decimal("40")
    assert lot_state(database, b)["available_quantity"] == Decimal("50")
    ancestry = service.query("lineage", TENANT, ACTOR, {"lot_key": b, "direction": "upstream"})
    assert harvested["lot"] in json.dumps(ancestry, default=str)


def test_unbalanced_event_rolls_back_inventory_event_and_outbox(service, database, harvested):
    child = lot(service)
    before = {t: table_count(database, t) for t in ("events", "outbox", "idempotency", "material_ancestry")}
    with pytest.raises(error_type()):
        event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], "50")], outputs=[flow(child, "51")])
    assert before == {t: table_count(database, t) for t in before}
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("100")
    assert lot_state(database, child)["produced_quantity"] == 0


@pytest.mark.parametrize("amount", ["0", "-1", "101"])
def test_zero_negative_or_excess_input_never_consumes_stock(service, database, harvested, amount):
    child = lot(service)
    with pytest.raises(error_type()):
        event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], amount)], outputs=[flow(child, amount)])
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("100")


def test_incompatible_units_rejected_without_invented_conversion(service, database, harvested):
    child = lot(service, unit="L")
    with pytest.raises(error_type()):
        event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], "10")], outputs=[flow(child, "10", "L")])
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("100")


def test_new_output_identity_prevents_material_cycle(service, database, harvested):
    child = lot(service)
    event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], "20")], outputs=[flow(child, "20")])
    with pytest.raises(error_type()):
        event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(child, "5")], outputs=[flow(harvested["lot"], "5")])
    assert lot_state(database, child)["available_quantity"] == Decimal("20")


def test_concurrent_overconsumption_allows_exactly_one_writer(service, database, harvested):
    children = [lot(service, "并发合成甲"), lot(service, "并发合成乙")]
    def consume(child):
        try:
            event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], "60")], outputs=[flow(child, "60")])
            return "committed"
        except error_type():
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, children))
    assert sorted(results) == ["committed", "rejected"]
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("40")
    assert sum(lot_state(database, c)["available_quantity"] for c in children) == Decimal("60")


def test_packaging_is_not_material_ancestry(service, database, harvested):
    container = entity(service, "package", "合成包装")
    before = table_count(database, "material_ancestry")
    event(service, "package", harvested["evidence"], participants=[{"entity_key": container, "role": "container"}, {"entity_key": harvested["lot"], "role": "contained_item"}])
    assert table_count(database, "material_ancestry") == before
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("100")


def test_partial_receipts_do_not_duplicate_inventory(service, database, harvested):
    sent = event(service, "ship", harvested["evidence"], items=[flow(harvested["lot"], "30")])
    event(service, "receive", harvested["evidence"], shipment_id=sent["id"], items=[flow(harvested["lot"], "12")])
    event(service, "receive", harvested["evidence"], shipment_id=sent["id"], items=[flow(harvested["lot"], "18")])
    state = lot_state(database, harvested["lot"])
    assert state["available_quantity"] == Decimal("70")
    assert state["received_quantity"] == Decimal("30")
    with pytest.raises(error_type()):
        event(service, "receive", harvested["evidence"], shipment_id=sent["id"], items=[flow(harvested["lot"], "1")])


def publish(service, harvested, assertions=None):
    return mutate(service, "publish", {"lot_key": harvested["lot"], "summary": {"product_name": "合成稻米", "origin": "合成农场", "description": "仅工程测试"},
        "assertion_ids": assertions or [], "evidence_ids": [harvested["evidence"]]})


def test_candidate_assertion_cannot_be_published(service, harvested):
    assertion = mutate(service, "create_assertion", {"subject_key": harvested["lot"], "predicate_id": "quality.synthetic_claim", "value": {"public_text": "仅合成候选声明"}, "evidence_ids": [harvested["evidence"]], "origin": "reported"})
    with pytest.raises(error_type()):
        publish(service, harvested, [assertion["id"]])
    mutate(service, "review_assertion", {"assertion_id": assertion["id"], "status": "accepted", "rationale": "合成审查测试"})
    assert publish(service, harvested, [assertion["id"]])["public_code"]


def test_public_projection_excludes_raw_evidence_and_internal_identity(service, harvested):
    publication = publish(service, harvested)
    public = service.public_trace(publication["public_code"])
    encoded = json.dumps(public, ensure_ascii=False, default=str)
    for secret in ("PRIVATE_SENTINEL", "不得公开", "private.example", harvested["lot"], harvested["batch"], harvested["evidence"], ACTOR["id"], TENANT):
        assert secret not in encoded
    assert "合成稻米" in encoded


def test_evidence_withdrawal_preserves_history_but_blocks_public_content(service, database, harvested):
    publication = publish(service, harvested)
    before = table_count(database, "publications")
    mutate(service, "withdraw_evidence", {"evidence_id": harvested["evidence"], "reason": "合成报告撤回"})
    assert table_count(database, "publications") == before
    try:
        public = service.public_trace(publication["public_code"])
    except error_type() as exc:
        assert exc.status in (404, 410)
    else:
        assert public["status"] in ("withdrawn", "unavailable", "evidence_withdrawn")
        assert public["data"]["quality_statements"] == []
        assert "private.example" not in json.dumps(public)


def test_upstream_recall_reaches_published_descendants(service, database, harvested):
    child = lot(service, "合成成品")
    event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], "25")], outputs=[flow(child, "25")])
    publication = publish(service, {**harvested, "lot": child})
    recalled = mutate(service, "recall", {"lot_key": harvested["lot"], "reason": "合成上游召回"})
    assert child in json.dumps(recalled, default=str)
    public = service.public_trace(publication["public_code"])
    assert public["status"] in ("recalled", "recall")
    assert public["data"]["quality_statements"] == []


def test_restart_reads_committed_identity(service, database):
    from agri.service import Service
    obj = entity(service, name="合成重启持久化对象")
    replacement_service = Service(database)
    assert replacement_service.query("entity", TENANT, ACTOR, {"entity_key": obj})["entity_key"] == obj


def test_multi_output_transform_does_not_invent_source_proportions(service, database, harvested):
    second_source = lot(service, "合成另一原料")
    event(service, "harvest", harvested["evidence"], participants=[{"entity_key": harvested["batch"], "role": "production_origin"}], outputs=[flow(second_source, "20")])
    first_output, second_output = lot(service, "合成混合甲"), lot(service, "合成混合乙")
    event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], "30"), flow(second_source, "20")], outputs=[flow(first_output, "25"), flow(second_output, "25")])
    with database.transaction() as tx:
        rows = tx.execute("SELECT * FROM material_ancestry WHERE tenant_id=%s AND output_lot_key=%s", (TENANT, first_output)).fetchall()
    assert {str(row["input_lot_key"]) for row in rows} == {harvested["lot"], second_source}
    assert all(row["allocation_quantity"] is None for row in rows)
    assert lot_state(database, first_output)["available_quantity"] == Decimal("25")


def test_transformation_requires_an_explicit_loss_account(service, database, harvested):
    output = lot(service, "合成加工品")
    with pytest.raises(error_type()):
        event(service, "transform", harvested["evidence"], inputs=[flow(harvested["lot"], "10")], outputs=[flow(output, "10")])
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("100")


def test_existing_package_release_cannot_be_silently_overwritten(service):
    package = {"package_id": "test.immutable", "version": "1.0.0", "namespace": "https://test.example/immutable/",
               "types": [{"type_id": "https://test.example/immutable/Field", "identity_type": "field", "label": "原合成定义"}], "predicates": []}
    mutate(service, "register_package", package)
    amended = deepcopy(package)
    amended["types"][0]["label"] = "偷偷更改定义"
    with pytest.raises(error_type()) as caught:
        mutate(service, "register_package", amended)
    assert caught.value.status == 409


def test_split_and_merge_preserve_quantities_and_source_identity(service, database, harvested):
    first, second, merged = lot(service, "拆批甲"), lot(service, "拆批乙"), lot(service, "并批成品")
    event(service, "split", harvested["evidence"], inputs=[flow(harvested["lot"], "100")], outputs=[flow(first, "40"), flow(second, "60")])
    event(service, "merge", harvested["evidence"], inputs=[flow(first, "40"), flow(second, "60")], outputs=[flow(merged, "100")])
    assert lot_state(database, harvested["lot"])["available_quantity"] == 0
    assert lot_state(database, first)["available_quantity"] == 0
    assert lot_state(database, second)["available_quantity"] == 0
    assert lot_state(database, merged)["available_quantity"] == Decimal("100")
    with database.transaction() as tx:
        rows = tx.execute("SELECT input_lot_key FROM material_ancestry WHERE tenant_id=%s AND output_lot_key=%s", (TENANT, merged)).fetchall()
    assert {str(row["input_lot_key"]) for row in rows} == {first, second}


def test_dynamic_set_changes_while_snapshot_members_remain_frozen(service):
    first = entity(service, "field", "合成集合甲")
    dynamic = mutate(service, "create_object_set", {"name": "合成动态集合", "mode": "dynamic", "filter": {"entity_type": "field"}})
    frozen = mutate(service, "create_object_set", {"name": "合成固定快照", "mode": "snapshot", "member_keys": [first]})
    original_members = deepcopy(frozen["members"])
    second = entity(service, "field", "合成集合乙")
    dynamic_result = service.query("object_sets", TENANT, ACTOR, {"id": dynamic["id"]})["items"][0]
    frozen_result = service.query("object_sets", TENANT, ACTOR, {"id": frozen["id"]})["items"][0]
    assert {m["entity_key"] for m in dynamic_result["current_members"]} == {first, second}
    assert frozen_result["members"] == original_members
    assert frozen_result["members"][0]["revision"] >= 1


def test_change_cursor_resumes_without_duplicates_and_rejects_foreign_tenant(service):
    for index in range(3):
        entity(service, "field", "合成增量" + str(index))
    first = service.query("changes", TENANT, ACTOR, {"limit": 1})
    assert len(first["items"]) == 1
    second = service.query("changes", TENANT, ACTOR, {"limit": 100, "cursor": first["next_cursor"]})
    first_ids = {row["event_id"] for row in first["items"]}
    next_ids = {row["event_id"] for row in second["items"]}
    assert len(first_ids | next_ids) == 3
    assert not first_ids & next_ids
    replay = service.query("changes", TENANT, ACTOR, {"limit": 100, "cursor": first["next_cursor"]})
    assert replay["items"] == second["items"]
    with pytest.raises(error_type()) as caught:
        service.query("changes", "test-farm-b", {**ACTOR, "tenant_id": "test-farm-b"}, {"cursor": first["next_cursor"]})
    assert caught.value.status == 422


def test_unimplemented_historical_snapshot_is_rejected_not_fabricated(service):
    entity(service)
    with pytest.raises(error_type()) as caught:
        service.query("entities", TENANT, ACTOR, {"known_at": "2020-01-01T00:00:00Z"})
    assert caught.value.code == "historical_snapshot_unsupported"


@pytest.mark.parametrize("event_type", ["transform", "ship"])
def test_recalled_lot_cannot_be_processed_or_shipped(service, database, harvested, event_type):
    child = lot(service, "合成召回后禁止产出")
    mutate(service, "recall", {"lot_key": harvested["lot"], "reason": "合成停用"})
    before = {t: table_count(database, t) for t in ("events", "outbox")}
    with pytest.raises(error_type()) as caught:
        if event_type == "ship":
            event(service, "ship", harvested["evidence"], items=[flow(harvested["lot"], "10")])
        else:
            event(service, "transform", harvested["evidence"], loss_quantity="0", inputs=[flow(harvested["lot"], "10")], outputs=[flow(child, "10")])
    assert caught.value.status == 409
    assert caught.value.code == "lot_recalled"
    assert before == {t: table_count(database, t) for t in before}
    assert lot_state(database, harvested["lot"])["available_quantity"] == Decimal("100")


def accepted_claim(service, harvested, value):
    record = mutate(service, "create_assertion", {"subject_key": harvested["lot"], "predicate_id": "synthetic.water.do", "value": value, "evidence_ids": [harvested["evidence"]], "origin": "reported"})
    mutate(service, "review_assertion", {"assertion_id": record["id"], "status": "accepted", "rationale": "合成测试评估"})
    return record["id"]


def test_comparable_adopted_disagreement_blocks_selective_publication(service, harvested):
    first = accepted_claim(service, harvested, {"value": "1", "unit": "mg/L", "scope": "A", "public_text": "合成采样值一"})
    second = accepted_claim(service, harvested, {"value": "2", "unit": "mg/L", "scope": "A", "public_text": "合成采样值二"})
    bundle = service.query("trace_bundle", TENANT, ACTOR, {"lot_key": harvested["lot"]})
    assert bundle["conflicts"]
    assert {first, second}.issubset(set(bundle["conflicts"][0]["member_ids"]))
    with pytest.raises(error_type()) as caught:
        publish(service, harvested, [first])
    assert caught.value.code == "unresolved_assertion_conflict"


def test_scope_and_decimal_equivalence_prevent_false_conflicts(service, harvested):
    accepted_claim(service, harvested, {"value": "1", "unit": "mg/L", "scope": "A", "public_text": "合成一"})
    accepted_claim(service, harvested, {"value": "1.0", "unit": "mg/L", "scope": "A", "public_text": "合成等值不同写法"})
    accepted_claim(service, harvested, {"value": "2", "unit": "mg/L", "scope": "B", "public_text": "合成不同范围"})
    bundle = service.query("trace_bundle", TENANT, ACTOR, {"lot_key": harvested["lot"]})
    assert bundle["conflicts"] == []
