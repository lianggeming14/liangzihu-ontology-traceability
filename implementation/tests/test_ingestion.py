"""Ingestion boundary tests plus a real SQLite persisted partial-retry regression."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path

import pytest
from flask import Flask, jsonify

ENTITY = "ba7b7c5a-3e55-4a44-8e17-247b2a67018b"
EVIDENCE = "67590a65-4edf-4a32-9895-d9288fd8a31a"


class IngestionSpy:
    def __init__(self):
        self.calls = []

    def mutate(self, action, tenant, actor, payload, key):
        self.calls.append((action, tenant, deepcopy(actor), deepcopy(payload), key))
        return {"id": EVIDENCE, "synthetic": True}


@pytest.fixture()
def ingest(tmp_path):
    from agri.ingestion import create_ingestion_blueprint
    from agri.service import DomainError
    original = Path(__file__).resolve().parents[1] / "contracts" / "input-schemas.json"
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "input-schemas.json").write_bytes(original.read_bytes())
    spy = IngestionSpy()
    context = {"actor": {"id": "tester", "tenant_id": "tenant-a", "roles": ["operator"]}}
    app = Flask(__name__)
    app.config.update(TESTING=True, MAX_CONTENT_LENGTH=2 * 1024 * 1024)

    @app.errorhandler(DomainError)
    def error(exc):
        return jsonify({"error": {"code": exc.code, "message": exc.message}}), exc.status

    app.register_blueprint(create_ingestion_blueprint(spy, lambda: context["actor"], tmp_path))
    return app.test_client(), spy, context, tmp_path


def observation(origin="measured"):
    return {"record_kind": "observation", "payload": {
        "subject_key": ENTITY, "property_id": "dissolved_oxygen",
        "value": {"value": "4.2", "unit": "mg/L"},
        "observed_at": "2026-10-11T00:00:00Z", "method": "synthetic-probe",
        "origin": origin, "evidence_ids": [EVIDENCE]}}


def records(client, source, values, key="batch-1"):
    return client.post("/api/v1/ingestion/records",
        json={"source_kind": source, "records": values, "synthetic": True},
        headers={"Idempotency-Key": key})


def upload(client, content=b"synthetic evidence", **form):
    key = form.pop("key", "asset-1")
    filename = form.pop("filename", "evidence.txt")
    return client.post("/api/v1/ingestion/assets",
        data={"file": (BytesIO(content), filename), "source_kind": "document", **form},
        headers={"Idempotency-Key": key})


def test_ingestion_needs_authentication(ingest):
    client, spy, context, _ = ingest
    context["actor"] = None
    assert records(client, "sensor", [observation()]).status_code == 401
    assert upload(client).status_code == 401
    assert spy.calls == []


@pytest.mark.parametrize("source", ["image", "video", "remote_sensing"])
def test_machine_vision_cannot_claim_direct_measurement(ingest, source):
    client, spy, _, _ = ingest
    response = records(client, source, [observation("measured")])
    assert response.status_code == 200
    assert response.json["data"]["accepted_count"] == 1
    assert spy.calls[0][0] == "create_observation"
    assert spy.calls[0][3]["origin"] == "estimated"


def test_weather_forecast_is_a_candidate_assertion(ingest):
    client, spy, _, _ = ingest
    response = records(client, "weather", [{"record_kind": "forecast", "payload": {
        "subject_key": ENTITY, "predicate_id": "forecast_rainfall",
        "value": {"value": "20", "unit": "mm"}, "origin": "measured",
        "evidence_ids": [EVIDENCE]}}])
    assert response.status_code == 200
    assert spy.calls[0][0] == "create_assertion"
    assert spy.calls[0][3]["origin"] == "forecast"
    assert "status" not in spy.calls[0][3]


def test_missing_evidence_is_rejected_without_mutation(ingest):
    client, spy, _, _ = ingest
    item = observation()
    item["payload"]["evidence_ids"] = []
    response = records(client, "sensor", [item])
    assert response.status_code == 200
    receipt = response.json["data"]["receipts"][0]
    assert receipt["status"] == "rejected"
    assert receipt["error"]["code"] == "evidence_required"
    assert spy.calls == []


def test_batch_partials_and_idempotency_scope_are_explicit(ingest):
    client, spy, _, _ = ingest
    response = records(client, "sensor", [observation(), {"record_kind": "unknown", "payload": {}}])
    body = response.json["data"]
    assert body["transaction_scope"] == "per_record"
    assert body["accepted_count"] == 1
    assert [r["status"] for r in body["receipts"]] == ["accepted", "rejected"]
    assert len(spy.calls) == 1
    assert spy.calls[0][-1] == "batch-1:0"
    records(client, "sensor", [observation()])
    assert spy.calls[1][-1] == "batch-1:0"


@pytest.mark.parametrize("values", [[], [observation()] * 101])
def test_batch_size_is_bounded(ingest, values):
    client, spy, _, _ = ingest
    assert records(client, "sensor", values).status_code == 422
    assert spy.calls == []


def test_unknown_source_is_not_inferred(ingest):
    client, spy, _, _ = ingest
    assert records(client, "unregistered-kind", [observation()]).status_code == 422
    assert spy.calls == []


def test_viewer_cannot_upload_or_create_raw_files(ingest):
    client, spy, context, base = ingest
    context["actor"]["roles"] = ["viewer"]
    assert upload(client).status_code == 403
    assert not (base / "data").exists()
    assert spy.calls == []


def test_upload_is_content_addressed_and_tenant_isolated(ingest):
    client, spy, context, base = ingest
    content = b"synthetic immutable material"
    assert upload(client, content, filename="../../escape.txt").status_code == 200
    assert upload(client, content).status_code == 200
    tenant_a = hashlib.sha256(b"tenant-a").hexdigest()
    digest = hashlib.sha256(content).hexdigest()
    target = base / "data" / "assets" / tenant_a / digest
    assert target.read_bytes() == content
    assert len(list(target.parent.iterdir())) == 1
    assert not (base / "escape.txt").exists()
    context["actor"]["tenant_id"] = "tenant-b"
    assert upload(client, content).status_code == 200
    tenant_b = hashlib.sha256(b"tenant-b").hexdigest()
    assert (base / "data" / "assets" / tenant_b / digest).read_bytes() == content
    assert spy.calls[-1][1] == "tenant-b"
    assert spy.calls[-1][3]["uri"] == "asset://" + digest


def test_empty_or_oversized_upload_is_rejected(ingest):
    client, spy, _, _ = ingest
    assert upload(client, b"").status_code == 422
    assert upload(client, b"x" * (2 * 1024 * 1024 + 1)).status_code == 413
    assert spy.calls == []


def test_asset_key_is_bounded(ingest):
    client, spy, _, _ = ingest
    assert upload(client, key="k" * 201).status_code == 422
    assert spy.calls == []


def test_invalid_asset_metadata_does_not_create_an_orphan(ingest):
    client, spy, _, base = ingest
    assert upload(client, source_id="").status_code == 422
    assets = base / "data" / "assets"
    assert not assets.exists() or not any(p.is_file() for p in assets.rglob("*"))
    assert spy.calls == []


def test_partial_batch_retry_reuses_success_and_commits_corrected_record_once(tmp_path):
    """Real SQLite/Service regression; fixes retain base key and record indexes."""
    from agri.ingestion import create_ingestion_blueprint
    from agri.service import DomainError, Service
    from agri.sqlite_db import SQLiteDatabase

    db = SQLiteDatabase("sqlite:///" + str(tmp_path / "partial-batch.db"))
    db.migrate()
    service = Service(db)
    actor = {"id":"real-retry-tester","tenant_id":"retry-tenant","roles":["admin"]}
    entity = service.mutate("create_entity","retry-tenant",actor,
        {"entity_type":"field","name":"Synthetic retry field"},"fixture:entity")
    evidence = service.mutate("create_evidence","retry-tenant",actor,
        {"kind":"document","uri":"urn:synthetic:retry-evidence",
         "content_hash":hashlib.sha256(b"synthetic retry evidence").hexdigest(),
         "metadata":{"synthetic":True}},"fixture:evidence")

    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.errorhandler(DomainError)
    def failure(exc):
        return jsonify({"error":{"code":exc.code}}), exc.status

    base = Path(__file__).resolve().parents[1]
    app.register_blueprint(create_ingestion_blueprint(service, lambda: actor, base))
    client = app.test_client()
    first = observation()
    first["payload"]["subject_key"] = entity["entity_key"]
    first["payload"]["evidence_ids"] = [evidence["id"]]
    second = deepcopy(first)
    second["payload"]["value"]["value"] = "4.3"
    second["payload"]["evidence_ids"] = ["00000000-0000-4000-8000-000000000001"]
    initial = records(client,"sensor",[first,second],key="same-form-batch").json["data"]
    assert [receipt["status"] for receipt in initial["receipts"]] == ["accepted","rejected"]
    successful_id = initial["receipts"][0]["result"]["id"]

    second["payload"]["evidence_ids"] = [evidence["id"]]
    retried = records(client,"sensor",[first,second],key="same-form-batch").json["data"]
    assert [receipt["status"] for receipt in retried["receipts"]] == ["accepted","accepted"]
    assert retried["receipts"][0]["result"]["id"] == successful_id
    assert retried["receipts"][1]["result"]["id"] != successful_id
    with db.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) AS n FROM observations WHERE tenant_id=%s",
                          ("retry-tenant",)).fetchone()["n"] == 2
        assert tx.execute("SELECT COUNT(*) AS n FROM outbox WHERE tenant_id=%s AND event_type=%s",
                          ("retry-tenant","create_observation")).fetchone()["n"] == 2
        assert tx.execute("SELECT COUNT(*) AS n FROM idempotency WHERE tenant_id=%s AND idempotency_key IN (%s,%s)",
                          ("retry-tenant","same-form-batch:0","same-form-batch:1")).fetchone()["n"] == 2
