"""Synthetic HTTP/RTSP responses only; no real camera, gate, socket or vendor account is contacted."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from PIL import Image

from ops.edge_gateway import (
    Gateway, GatewayError, Outbox, ProcessLock, Response, encode, gate_data, iso,
    validate_config, checked_url, json_body, no_credentials_in_receipt,
)

DEVICE = "00000000-0000-4000-8000-000000000011"
POLICY = "00000000-0000-4000-8000-000000000022"
EVIDENCE = "00000000-0000-4000-8000-000000000033"
NOW = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)
ENV = {"TEST_API_URL": "http://localhost", "TEST_API_TOKEN": "synthetic-local-test",
       "TEST_SOURCE_URL": "https://source.example.invalid/read-only", "TEST_SOURCE_TOKEN": "synthetic-source-test"}


def sample_image():
    output = io.BytesIO()
    Image.new("RGB", (3, 3), (10, 100, 20)).save(output, format="PNG")
    return output.getvalue()


def configuration(adapter="http_snapshot"):
    device = {"device_id": DEVICE, "adapter": adapter, "enabled": True, "url_env": "TEST_SOURCE_URL",
              "source_id": "synthetic-edge", "mapping_version": "synthetic-v1"}
    if adapter == "http_gate_json":
        device.update(state_field="telemetry.state", position_field="telemetry.position",
                      timestamp_field="telemetry.time", state_map={"O": "open", "C": "closed", "P": "partial"},
                      position_scale="100", position_offset="0")
    return validate_config({"schema_version": "1.0", "api_base_url_env": "TEST_API_URL",
                            "api_token_env": "TEST_API_TOKEN", "devices": [device]})


def slot(at=NOW - timedelta(seconds=30), priority="routine"):
    return {"slot_id": hashlib.sha256((iso(at) + priority).encode()).hexdigest(), "slot_at": iso(at),
            "policy_id": POLICY, "device_id": DEVICE, "record_type": "camera_snapshot",
            "priority": priority, "focus_labels": ["合成重点"] if priority == "focus" else []}


class FakeTransport:
    def __init__(self, slots=None, raw=None, fail_stage=None):
        self.slots = [slot()] if slots is None else slots
        self.raw = sample_image() if raw is None else raw
        self.calls = []
        self.fail_stage = fail_stage
        self.failed = False
        self.source_status = 200
        self.truncated = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, deepcopy(kwargs)))
        if url.startswith(ENV["TEST_SOURCE_URL"]):
            return Response(self.source_status, self.raw, {})
        if "/device-captures/due?" in url:
            return Response(200, encode({"data": {"items": self.slots, "has_more": self.truncated,
                                                  "truncated": self.truncated}}), {})
        stage = "asset" if url.endswith("/ingestion/assets") else "record"
        if self.fail_stage == stage and not self.failed:
            self.failed = True
            raise GatewayError("http_transport_failed")
        return Response(201, encode({"data": {"id": EVIDENCE if stage == "asset" else str(uuid4())}}), {})

    def calls_for(self, fragment):
        return [entry for entry in self.calls if fragment in entry[1]]


def test_snapshot_actual_fetch_time_is_distinct_from_slot_and_no_old_slot_recapture(tmp_path):
    config, transport = configuration(), FakeTransport()
    box = Outbox(tmp_path / "outbox.sqlite")
    try:
        worker = Gateway(config, box, transport=transport, env=ENV, clock=lambda: NOW)
        first = worker.run_once()
        assert first["delivered"] == 1 and first["control_supported"] is False
        record_call = transport.calls_for("/device-records")[0]
        record = json.loads(record_call[2]["body"])
        assert record["captured_at"] == iso(NOW)
        assert record["slot_at"] == slot()["slot_at"]
        assert record["captured_at"] != record["slot_at"]
        assert record["source_record_id"] == slot()["slot_id"]
        assert "fetch_time_not_verified_exposure_time" in record["note"]
        assert record["evidence_ids"] == [EVIDENCE]
        assert transport.calls_for("/ingestion/assets")[0][2]["fields"]["source_kind"] == "image"
        assert worker.run_once()["new_jobs"] == 0
        assert len(transport.calls_for(ENV["TEST_SOURCE_URL"])) == 1
        assert all(call[0] == "GET" for call in transport.calls_for(ENV["TEST_SOURCE_URL"]))
    finally:
        box.close()


@pytest.mark.parametrize("stage", ["asset", "record"])
def test_restart_retries_original_bytes_body_and_idempotency_keys_without_recapture(tmp_path, stage):
    config, transport = configuration(), FakeTransport(fail_stage=stage)
    box_path = tmp_path / "outbox.sqlite"
    box = Outbox(box_path)
    worker = Gateway(config, box, transport=transport, env=ENV, clock=lambda: NOW)
    assert worker.run_once()["pending_or_failed"] == 1
    pending = dict(box.db.execute("SELECT * FROM jobs").fetchone())
    assert pending["asset_bytes"] == transport.raw
    box.close()
    transport.raw = b"source has now changed and must not be read"
    box = Outbox(box_path)
    try:
        worker = Gateway(config, box, transport=transport, env=ENV, clock=lambda: NOW + timedelta(seconds=10))
        assert worker.run_once()["delivered"] == 1
        calls = transport.calls_for("/ingestion/assets" if stage == "asset" else "/device-records")
        assert len(calls) == 2
        assert calls[0][2]["headers"]["Idempotency-Key"] == calls[1][2]["headers"]["Idempotency-Key"]
        if stage == "asset":
            assert calls[0][2]["file"] == calls[1][2]["file"]
            assert calls[0][2]["fields"] == calls[1][2]["fields"]
        else:
            assert calls[0][2]["body"] == calls[1][2]["body"]
        assert len(transport.calls_for(ENV["TEST_SOURCE_URL"])) == 1
        assert box.db.execute("SELECT phase FROM jobs").fetchone()[0] == "delivered"
    finally:
        box.close()


def test_focus_takes_priority_and_only_one_new_capture_per_device(tmp_path):
    candidates = [slot(NOW - timedelta(seconds=10)), slot(NOW - timedelta(seconds=40), "focus")]
    transport, box = FakeTransport(candidates), Outbox(tmp_path / "outbox.sqlite")
    try:
        result = Gateway(configuration(), box, transport=transport, env=ENV, clock=lambda: NOW).run_once()
        assert result["new_jobs"] == 1
        record = json.loads(transport.calls_for("/device-records")[0][2]["body"])
        assert record["source_record_id"] == candidates[1]["slot_id"]
        assert box.watermark(DEVICE) == NOW - timedelta(seconds=10)
    finally:
        box.close()


def test_stale_future_and_video_slots_do_not_trigger_source_calls(tmp_path):
    video = {**slot(), "record_type": "camera_video"}
    transport = FakeTransport([slot(NOW - timedelta(hours=1)), slot(NOW + timedelta(seconds=10)), video])
    box = Outbox(tmp_path / "outbox.sqlite")
    try:
        result = Gateway(configuration(), box, transport=transport, env=ENV, clock=lambda: NOW).run_once()
        assert result["new_jobs"] == 0
        assert not transport.calls_for(ENV["TEST_SOURCE_URL"])
    finally:
        box.close()


def test_dense_due_response_is_refused_instead_of_selecting_incomplete_latest(tmp_path):
    transport, box = FakeTransport(), Outbox(tmp_path / "outbox.sqlite")
    transport.truncated = True
    try:
        result = Gateway(configuration(), box, transport=transport, env=ENV, clock=lambda: NOW).run_once()
        assert result["errors"] == ["due_window_too_dense"]
        assert not transport.calls_for(ENV["TEST_SOURCE_URL"])
    finally:
        box.close()


def test_gate_explicit_mapping_conversion_unknown_and_conflict():
    device = configuration("http_gate_json")["devices"][0]
    assert gate_data({"telemetry": {"state": "P", "position": "0.255"}}, device) == {"state": "partial", "position_pct": "25.500"}
    assert gate_data({"telemetry": {"state": "unsupported", "position": "1"}}, device) == {"state": "unknown", "position_pct": "100"}
    assert gate_data({"telemetry": {}}, device) == {"state": "unknown"}
    with pytest.raises(GatewayError, match="gate_state_position_conflict"):
        gate_data({"telemetry": {"state": "C", "position": "1"}}, device)
    with pytest.raises(GatewayError, match="invalid_gate_position"):
        gate_data({"telemetry": {"state": "P", "position": "NaN"}}, device)


def test_gate_vendor_time_and_raw_evidence_are_preserved(tmp_path):
    timestamp = NOW - timedelta(seconds=15)
    raw = encode({"telemetry": {"state": "P", "position": "0.25", "time": iso(timestamp)}, "synthetic": True})
    item = {**slot(), "record_type": "gate_status"}
    transport, box = FakeTransport([item], raw), Outbox(tmp_path / "outbox.sqlite")
    try:
        result = Gateway(configuration("http_gate_json"), box, transport=transport, env=ENV, clock=lambda: NOW).run_once()
        assert result["delivered"] == 1
        upload = transport.calls_for("/ingestion/assets")[0][2]
        assert upload["file"][1] == raw
        assert upload["fields"]["source_kind"] == "official_api"
        record = json.loads(transport.calls_for("/device-records")[0][2]["body"])
        assert record["captured_at"] == iso(timestamp)
        assert "timestamp_basis=vendor_timestamp" in record["note"]
    finally:
        box.close()


@pytest.mark.parametrize("raw", [
    b'{"telemetry":{"state":"O","position":"1","time":"2026-10-13T08:00:00"}}',
    b'{"telemetry":{"state":"O","position":"1","time":"2026-10-01T00:00:00Z"}}',
    b'{"telemetry":{"state":"O"},"password":"synthetic-do-not-archive"}',
])
def test_bad_time_or_credentials_remain_failed_without_upload(tmp_path, raw):
    transport = FakeTransport([{**slot(), "record_type": "gate_status"}], raw)
    box = Outbox(tmp_path / "outbox.sqlite")
    try:
        result = Gateway(configuration("http_gate_json"), box, transport=transport, env=ENV, clock=lambda: NOW).run_once()
        assert result["pending_or_failed"] == 1
        assert not transport.calls_for("/ingestion/assets")
        assert box.db.execute("SELECT count(*) FROM jobs WHERE phase='capture_pending'").fetchone()[0] == 1
    finally:
        box.close()


@pytest.mark.parametrize("status,raw,expected", [
    (302, sample_image(), "redirect_refused"),
    (200, b"x" * (1536 * 1024 + 1), "response_too_large"),
    (200, b"<html>not an image</html>", "invalid_snapshot_image"),
], ids=["redirect", "too-large", "not-image"])
def test_source_boundary_rejects_redirect_size_and_nonimage(tmp_path, status, raw, expected):
    transport, box = FakeTransport(raw=raw), Outbox(tmp_path / "outbox.sqlite")
    transport.source_status = status
    try:
        result = Gateway(configuration(), box, transport=transport, env=ENV, clock=lambda: NOW).run_once()
        assert expected in result["errors"]
        assert not transport.calls_for("/ingestion/assets")
    finally:
        box.close()


def test_failed_capture_expires_without_backdating_and_preserves_diagnostic(tmp_path):
    clock = [NOW]
    transport, box = FakeTransport(raw=b"bad image"), Outbox(tmp_path / "outbox.sqlite")
    try:
        worker = Gateway(configuration(), box, transport=transport, env=ENV, clock=lambda: clock[0])
        assert worker.run_once()["pending_or_failed"] == 1
        clock[0] += timedelta(minutes=5)
        result = worker.run_once()
        assert result["expired_without_capture"] == 1
        row = box.db.execute("SELECT * FROM jobs").fetchone()
        assert row["phase"] == "expired_no_capture"
        assert row["last_error"] == "slot_expired_before_capture"
        assert not transport.calls_for("/device-records")
    finally:
        box.close()


def test_rtsp_transport_is_explicit_optional_and_uses_same_upload_contract(tmp_path):
    config, box = configuration("rtsp_snapshot"), Outbox(tmp_path / "outbox.sqlite")
    env = {**ENV, "TEST_SOURCE_URL": "rtsp://camera.example.invalid/main"}
    calls, transport = [], FakeTransport()
    def controlled_rtsp(url, **kwargs):
        calls.append((url, kwargs))
        return sample_image()
    try:
        result = Gateway(config, box, transport=transport, env=env, clock=lambda: NOW,
                         rtsp_runner=controlled_rtsp).run_once()
        assert result["delivered"] == 1 and len(calls) == 1
        assert not transport.calls_for("source.example.invalid")
    finally:
        box.close()


def test_plaintext_secrets_and_state_path_escape_configuration_are_rejected():
    base = {"schema_version": "1.0", "api_base_url_env": "TEST_API_URL", "api_token_env": "TEST_API_TOKEN", "devices": []}
    for changes in ({"api_token": "synthetic-secret"}, {"state_directory": "../../outside"}, {"api_base_url_env": "https://invalid"}):
        with pytest.raises(GatewayError):
            validate_config({**base, **changes})
    with pytest.raises(GatewayError, match="http_url_credentials_forbidden"):
        checked_url("https://synthetic-user:synthetic-secret@example.invalid/", {"https"})


def test_single_outbox_process_lock_is_exclusive(tmp_path):
    with ProcessLock(tmp_path / "gateway.lock"):
        with pytest.raises(GatewayError, match="gateway_already_running"):
            with ProcessLock(tmp_path / "gateway.lock"):
                pass


@pytest.mark.parametrize("kind", ["camera", "gate"])
def test_real_flask_sqlite_asset_and_device_receipt_with_synthetic_source(tmp_path, kind):
    """Actual application/SQLite pipeline; only the source HTTP response is a controlled double."""
    from agri.app import create_app
    app = create_app({"TESTING": True, "DATABASE_URL": "sqlite:///" + str(tmp_path / "api.sqlite"),
                      "ASSET_ROOT": tmp_path / "assets", "DEMO_MODE": False,
                      "AUTH_TOKENS": {"synthetic-local-test": {"id": "gateway-test", "tenant_id": "gateway-tenant", "roles": ["admin"]}}})
    client = app.test_client()
    def post(url, payload):
        response = client.post(url, json=payload, headers={"Authorization": "Bearer synthetic-local-test",
                                                           "Idempotency-Key": str(uuid4())})
        assert response.status_code in (200, 201), response.json
        return response.json["data"]
    bound = post("/api/v1/ontology/entities", {"entity_type": "field", "name": "合成网关联调田块"})["entity_key"]
    device = post("/api/v1/devices", {"name": "合成网关联调设备", "device_kind": kind,
                                     "source_id": "synthetic-edge", "external_device_id": "synthetic-" + kind,
                                     "bound_entity_key": bound})
    now = datetime.now(timezone.utc).replace(microsecond=0)
    record_type = "camera_snapshot" if kind == "camera" else "gate_status"
    post("/api/v1/device-policies", {"device_id": device["id"], "name": "合成采集策略", "record_type": record_type,
                                   "start_at": iso(now - timedelta(seconds=60)), "interval_seconds": 60,
                                   "focus_windows": []})
    config = configuration("http_snapshot" if kind == "camera" else "http_gate_json")
    config["devices"][0]["device_id"] = device["id"]
    raw = sample_image() if kind == "camera" else encode({"telemetry": {"state": "P", "position": "0.25", "time": iso(now)},
                                                         "synthetic": True})
    class FlaskTransport:
        def request(self, method, url, **kwargs):
            if url.startswith(ENV["TEST_SOURCE_URL"]):
                return Response(200, raw, {})
            parsed = urlsplit(url)
            options = {"headers": kwargs.get("headers", {})}
            if kwargs.get("file"):
                name, content, mime = kwargs["file"]
                options["data"] = {**kwargs["fields"], "file": (io.BytesIO(content), name, mime)}
                options["content_type"] = "multipart/form-data"
            elif kwargs.get("body") is not None:
                options["data"] = kwargs["body"]
            response = client.open(parsed.path + ("?" + parsed.query if parsed.query else ""), method=method, **options)
            return Response(response.status_code, response.data, dict(response.headers))
    box = Outbox(tmp_path / "edge.sqlite")
    try:
        result = Gateway(config, box, transport=FlaskTransport(), env=ENV, clock=lambda: now).run_once()
        assert result["delivered"] == 1, result
        service = app.extensions["agri_service"]
        with service.db.transaction() as tx:
            assert tx.execute("SELECT COUNT(*) AS n FROM device_records").fetchone()["n"] == 1
            assert tx.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"] == 1
            assert tx.execute("SELECT COUNT(*) AS n FROM observations").fetchone()["n"] == (2 if kind == "gate" else 0)
        assert len(list((tmp_path / "assets").glob("*/*"))) >= 1
    finally:
        box.close()


@pytest.mark.parametrize("position", ["1e1000000", "0.0000000001"])
def test_gate_position_precision_and_exponent_do_not_silently_round(position):
    device = configuration("http_gate_json")["devices"][0]
    with pytest.raises(GatewayError, match="invalid_gate_position"):
        gate_data({"telemetry": {"state": "P", "position": position}}, device)


def test_outbox_capacity_is_checked_before_reading_source(tmp_path):
    config, transport = configuration(), FakeTransport()
    config["max_pending_bytes"] = config["max_asset_bytes"]
    box = Outbox(tmp_path / "outbox.sqlite")
    try:
        occupied = box.enqueue(slot(NOW - timedelta(seconds=110)), NOW - timedelta(seconds=110), NOW, 200)
        with box.db:
            box.db.execute("UPDATE jobs SET phase='delivered',asset_bytes=? WHERE job_key=?",
                           (b"held-evidence", occupied["job_key"]))
        result = Gateway(config, box, transport=transport, env=ENV, clock=lambda: NOW).run_once()
        assert "outbox_byte_budget_reached" in result["errors"]
        assert not transport.calls_for(ENV["TEST_SOURCE_URL"])
        assert box.db.execute("SELECT count(*) FROM jobs WHERE phase='capture_pending'").fetchone()[0] == 1
    finally:
        box.close()


def test_rtsp_requires_explicit_ffmpeg_binary_and_preserves_pending(tmp_path):
    box, transport = Outbox(tmp_path / "outbox.sqlite"), FakeTransport()
    try:
        worker = Gateway(configuration("rtsp_snapshot"), box, transport=transport,
                         env={**ENV, "TEST_SOURCE_URL": "rtsp://camera.example.invalid/main"},
                         clock=lambda: NOW)
        result = worker.run_once()
        assert "required_environment_not_set" in result["errors"]
        assert not transport.calls_for("/ingestion/assets")
        assert box.db.execute("SELECT phase FROM jobs").fetchone()[0] == "capture_pending"
    finally:
        box.close()
