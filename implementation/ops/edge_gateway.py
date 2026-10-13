#!/usr/bin/env python3
"""Explicitly run a read-only edge collector; no actuator command API exists here."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from urllib.parse import urlencode, urlsplit
from uuid import UUID

IMPL = Path(__file__).resolve().parents[1]
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,100}$")
MAX_ASSET = 1536 * 1024  # Conservative per-snapshot budget, independently below the server limit.
GATE_STATES = {"open", "closed", "partial", "unknown"}
ADAPTERS = {"http_snapshot", "rtsp_snapshot", "http_gate_json"}
SENSITIVE_KEYS = {"password", "authorization", "accesstoken", "refreshtoken", "appsecret",
                  "apikey", "secret", "secretkey", "clientsecret", "token", "credential", "credentials"}
SECRET_FORMATS = (re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
                  re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"))
UTC = timezone.utc


class GatewayError(Exception):
    """Only fixed, non-secret error codes may cross this boundary."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def utcnow():
    return datetime.now(UTC)


def iso(value: datetime):
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        raise GatewayError("invalid_source_time")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GatewayError("invalid_source_time") from None
    if result.tzinfo is None:
        raise GatewayError("source_timezone_required")
    return result.astimezone(UTC)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise GatewayError("invalid_device_or_policy_id") from None


def checked_url(value, schemes, *, base=False):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise GatewayError("invalid_configured_url")
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError:
        raise GatewayError("invalid_configured_url") from None
    if parts.scheme not in schemes or not parts.hostname or parts.fragment:
        raise GatewayError("invalid_configured_url")
    # RTSP credentials may be supplied through an environment-only URL. HTTP uses headers.
    if parts.scheme in {"http", "https"} and (parts.username is not None or parts.password is not None):
        raise GatewayError("http_url_credentials_forbidden")
    if base and (parts.query or parts.path not in {"", "/"}):
        raise GatewayError("api_base_must_be_origin")
    return value.rstrip("/") if base else value


def env_value(env, name, *, optional=False):
    if not isinstance(name, str) or not ENV_NAME.fullmatch(name):
        raise GatewayError("invalid_environment_reference")
    value = env.get(name)
    if not value:
        if optional:
            return None
        raise GatewayError("required_environment_not_set")
    if "\r" in value or "\n" in value:
        raise GatewayError("invalid_environment_value")
    return value


def validate_config(config):
    if not isinstance(config, dict) or config.get("schema_version") != "1.0":
        raise GatewayError("unsupported_gateway_configuration")
    for key in ("api_base_url_env", "api_token_env"):
        if not ENV_NAME.fullmatch(str(config.get(key, ""))):
            raise GatewayError("invalid_environment_reference")
    rules = {
        "poll_seconds": (1, 3600, 30), "lookback_seconds": (1, 900, 120),
        "max_slot_age_seconds": (1, 900, 120), "http_timeout_seconds": (1, 120, 15),
        "max_asset_bytes": (1024, MAX_ASSET, MAX_ASSET),
        "max_pending_jobs": (1, 2000, 200), "max_pending_bytes": (1024, 512 * 1024 * 1024, 100 * 1024 * 1024),
        "retry_base_seconds": (1, 3600, 5), "max_jobs_per_pass": (1, 500, 50),
    }
    result = dict(config)
    for name, (low, high, default) in rules.items():
        value = config.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise GatewayError("invalid_gateway_limit")
        result[name] = value
    allowed_root = {"schema_version", "api_base_url_env", "api_token_env", "state_directory", "devices", *rules}
    if set(config) - allowed_root:
        raise GatewayError("unknown_gateway_configuration_field")
    if result["max_pending_bytes"] < result["max_asset_bytes"]:
        raise GatewayError("outbox_budget_below_one_asset")
    directory = config.get("state_directory", "data/edge-gateway")
    if not isinstance(directory, str) or Path(directory).is_absolute():
        raise GatewayError("invalid_state_directory")
    target = (IMPL / directory).resolve()
    if not target.is_relative_to((IMPL / "data").resolve()):
        raise GatewayError("state_directory_must_be_under_data")
    result["state_directory"] = str(target)
    devices = config.get("devices")
    if not isinstance(devices, list) or len(devices) > 200:
        raise GatewayError("invalid_device_configuration")
    ids, normalized = set(), []
    for raw in devices:
        if not isinstance(raw, dict):
            raise GatewayError("invalid_device_configuration")
        device = dict(raw)
        device["device_id"] = uuid(device.get("device_id"))
        if device["device_id"] in ids or device.get("adapter") not in ADAPTERS:
            raise GatewayError("invalid_or_duplicate_adapter")
        ids.add(device["device_id"])
        if type(device.get("enabled", False)) is not bool:
            raise GatewayError("invalid_device_enabled")
        for field in ("url_env",):
            if not ENV_NAME.fullmatch(str(device.get(field, ""))):
                raise GatewayError("invalid_environment_reference")
        if device.get("token_env") is not None and not ENV_NAME.fullmatch(str(device["token_env"])):
            raise GatewayError("invalid_environment_reference")
        # Literal URLs/tokens and arbitrary request bodies are never valid configuration fields.
        allowed = {"device_id", "adapter", "enabled", "url_env", "token_env", "source_id",
                   "mapping_version", "state_field", "position_field", "timestamp_field",
                   "state_map", "position_scale", "position_offset"}
        if set(device) - allowed:
            raise GatewayError("unknown_adapter_configuration_field")
        if not isinstance(device.get("source_id", ""), str) or not device["source_id"] or len(device["source_id"]) > 200:
            raise GatewayError("source_id_required")
        version = device.get("mapping_version")
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", version):
            raise GatewayError("mapping_version_required")
        if device["adapter"] == "rtsp_snapshot" and device.get("token_env"):
            raise GatewayError("rtsp_token_header_unsupported")
        if device["adapter"] != "http_gate_json" and any(k in device for k in {"state_field", "position_field", "timestamp_field", "state_map", "position_scale", "position_offset"}):
            raise GatewayError("gate_mapping_on_camera_adapter")
        if device["adapter"] == "http_gate_json":
            if not isinstance(device.get("state_field"), str) or not device["state_field"]:
                raise GatewayError("state_field_required")
            mapping = device.get("state_map")
            if not isinstance(mapping, dict) or not mapping or len(mapping) > 100:
                raise GatewayError("state_map_required")
            if any(not isinstance(k, str) or v not in GATE_STATES for k, v in mapping.items()):
                raise GatewayError("invalid_state_map")
            for name in ("position_field", "timestamp_field"):
                if device.get(name) is not None and not isinstance(device[name], str):
                    raise GatewayError("invalid_field_mapping")
            for name, default in (("position_scale", "1"), ("position_offset", "0")):
                try:
                    number = Decimal(str(device.get(name, default)))
                    if not number.is_finite():
                        raise InvalidOperation()
                except (InvalidOperation, ValueError):
                    raise GatewayError("invalid_position_conversion") from None
                device[name] = str(number)
        normalized.append(device)
    result["devices"] = normalized
    return result


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict


class RequestsTransport:
    """No redirects, implicit proxy credentials, cookie jar reuse, or unbounded body reads."""
    def request(self, method, url, *, headers=None, body=None, file=None, fields=None,
                timeout=15, max_bytes=MAX_ASSET):
        import requests
        try:
            with requests.Session() as session:
                session.trust_env = False
                files = None if file is None else {"file": file}
                with session.request(method, url, headers=headers, data=fields if files else body,
                                     files=files, timeout=(timeout, timeout), allow_redirects=False,
                                     stream=True) as response:
                    if 300 <= response.status_code < 400:
                        raise GatewayError("redirect_refused")
                    length = response.headers.get("Content-Length")
                    if length and (not length.isdigit() or int(length) > max_bytes):
                        raise GatewayError("response_too_large")
                    chunks, total, started = [], 0, time.monotonic()
                    for chunk in response.iter_content(65536):
                        total += len(chunk)
                        if total > max_bytes:
                            raise GatewayError("response_too_large")
                        if time.monotonic() - started > timeout:
                            raise GatewayError("response_deadline_exceeded")
                        chunks.append(chunk)
                    return Response(response.status_code, b"".join(chunks), dict(response.headers))
        except GatewayError:
            raise
        except requests.RequestException:
            # Do not include exceptions: they can embed source URLs or authentication details.
            raise GatewayError("http_transport_failed") from None


class Outbox:
    """The original captured bytes and exact POST body survive process restart."""
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          job_key TEXT PRIMARY KEY, device_id TEXT NOT NULL, slot_at TEXT NOT NULL,
          slot_json TEXT NOT NULL, phase TEXT NOT NULL, asset_bytes BLOB, mime TEXT,
          source_kind TEXT, source_id TEXT, record_json TEXT, evidence_id TEXT,
          asset_key TEXT NOT NULL, record_key TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          next_at TEXT NOT NULL, last_error TEXT, created_at TEXT NOT NULL, completed_at TEXT);
        CREATE TABLE IF NOT EXISTS device_watermarks (
          device_id TEXT PRIMARY KEY, slot_at TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def row(self, key):
        row = self.db.execute("SELECT * FROM jobs WHERE job_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def ready(self, now, limit):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM jobs WHERE phase IN ('capture_pending','asset_pending','record_pending') "
            "AND next_at<=? ORDER BY created_at,job_key LIMIT ?", (iso(now), limit))]

    def busy(self, device_id):
        return bool(self.db.execute(
            "SELECT 1 FROM jobs WHERE device_id=? AND phase IN ('capture_pending','asset_pending','record_pending')",
            (device_id,)).fetchone())

    def watermark(self, device_id):
        row = self.db.execute("SELECT slot_at FROM device_watermarks WHERE device_id=?", (device_id,)).fetchone()
        return parse_time(row["slot_at"]) if row else None

    def enqueue(self, slot, watermark, now, max_jobs):
        count = self.db.execute("SELECT count(*) FROM jobs WHERE phase NOT IN ('delivered','expired_no_capture')").fetchone()[0]
        if count >= max_jobs:
            raise GatewayError("outbox_job_budget_reached")
        key = hashlib.sha256((slot["device_id"] + ":" + slot["slot_id"]).encode()).hexdigest()
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO jobs(job_key,device_id,slot_at,slot_json,phase,asset_key,record_key,next_at,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (key, slot["device_id"], iso(parse_time(slot["slot_at"])), encode(slot).decode(),
                 "capture_pending", "edge-asset:" + key, "edge-record:" + key, iso(now), iso(now)))
            self.db.execute(
                "INSERT INTO device_watermarks(device_id,slot_at) VALUES(?,?) ON CONFLICT(device_id) "
                "DO UPDATE SET slot_at=MAX(slot_at,excluded.slot_at)", (slot["device_id"], iso(watermark)))
        return self.row(key)

    def reserve_check(self, max_asset, max_total):
        used = self.db.execute("SELECT COALESCE(sum(length(asset_bytes)),0) FROM jobs").fetchone()[0]
        if used + max_asset > max_total:
            raise GatewayError("outbox_byte_budget_reached")

    def store_capture(self, key, captured, source_id, max_bytes):
        used = self.db.execute("SELECT COALESCE(sum(length(asset_bytes)),0) FROM jobs").fetchone()[0]
        if used + len(captured["bytes"]) > max_bytes:
            raise GatewayError("outbox_byte_budget_reached")
        with self.db:
            self.db.execute(
                "UPDATE jobs SET phase='asset_pending',asset_bytes=?,mime=?,source_kind=?,source_id=?,record_json=?,"
                "attempts=0,last_error=NULL WHERE job_key=? AND phase='capture_pending'",
                (captured["bytes"], captured["mime"], captured["source_kind"], source_id,
                 encode(captured["record"]).decode(), key))

    def asset_received(self, key, evidence_id):
        row = self.row(key)
        record = json.loads(row["record_json"])
        record["evidence_ids"] = [uuid(evidence_id)]
        with self.db:
            self.db.execute(
                "UPDATE jobs SET phase='record_pending',evidence_id=?,record_json=?,attempts=0,last_error=NULL WHERE job_key=?",
                (evidence_id, encode(record).decode(), key))

    def delivered(self, key, now):
        with self.db:
            self.db.execute("UPDATE jobs SET phase='delivered',completed_at=?,asset_bytes=NULL,last_error=NULL WHERE job_key=?",
                            (iso(now), key))

    def failed(self, key, code, now, retry_base):
        row = self.row(key)
        attempts = row["attempts"] + 1
        delay = min(300, retry_base * (2 ** min(attempts - 1, 10)))
        with self.db:
            self.db.execute("UPDATE jobs SET attempts=?,last_error=?,next_at=? WHERE job_key=?",
                            (attempts, code, iso(now + timedelta(seconds=delay)), key))

    def expired(self, key):
        with self.db:
            self.db.execute("UPDATE jobs SET phase='expired_no_capture',last_error='slot_expired_before_capture' WHERE job_key=?",
                            (key,))


def json_body(body):
    try:
        value = json.loads(body.decode("utf-8"), parse_float=Decimal,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise GatewayError("invalid_json_response") from None
    if not isinstance(value, dict):
        raise GatewayError("json_object_required")
    return value


def field_value(payload, field, *, optional=False):
    if not field:
        return None
    current = payload
    for part in field.split("."):
        if not part or not isinstance(current, dict) or part not in current:
            if optional:
                return None
            raise GatewayError("mapped_field_missing")
        current = current[part]
    return current


def gate_data(payload, device):
    raw_state = field_value(payload, device["state_field"], optional=True)
    if isinstance(raw_state, bool):
        lookup = "true" if raw_state else "false"
    elif isinstance(raw_state, (str, int, Decimal)) and raw_state is not None:
        lookup = str(raw_state)
    else:
        lookup = None
    state = device["state_map"].get(lookup, "unknown")
    result = {"state": state}
    if device.get("position_field"):
        raw_position = field_value(payload, device["position_field"], optional=True)
        if raw_position is not None:
            try:
                if isinstance(raw_position, bool):
                    raise InvalidOperation()
                numbers = [Decimal(str(raw_position)), Decimal(device["position_scale"]),
                           Decimal(device["position_offset"])]
                if any(not n.is_finite() or len(n.as_tuple().digits) > 40
                       or abs(n.as_tuple().exponent) > 40 for n in numbers):
                    raise InvalidOperation()
                # Keep source conversion exact; never round to make an API value fit.
                with localcontext() as context:
                    context.prec = 100
                    position = numbers[0] * numbers[1] + numbers[2]
                if (not position.is_finite() or not Decimal(0) <= position <= Decimal(100)
                        or position.as_tuple().exponent < -9):
                    raise InvalidOperation()
            except (InvalidOperation, ValueError):
                raise GatewayError("invalid_gate_position") from None
            if (state == "open" and position != 100 or state == "closed" and position != 0
                    or state == "partial" and not 0 < position < 100):
                raise GatewayError("gate_state_position_conflict")
            result["position_pct"] = format(position, "f")
    return result


def no_credentials_in_receipt(payload, raw):
    if any(pattern.search(raw) for pattern in SECRET_FORMATS):
        raise GatewayError("credential_in_source_body")
    pending = [payload]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if re.sub(r"[_-]", "", key.lower()) in SENSITIVE_KEYS:
                    raise GatewayError("credential_in_source_body")
                if isinstance(value, (dict, list)):
                    pending.append(value)
        elif isinstance(item, list):
            pending.extend(item)


def image_mime(data):
    from PIL import Image
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG"} or image.width * image.height > 20000000:
                    raise GatewayError("unsupported_or_oversized_image")
                image.load()
                return "image/jpeg" if image.format == "JPEG" else "image/png"
    except GatewayError:
        raise
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise GatewayError("invalid_snapshot_image") from None


class Gateway:
    def __init__(self, config, outbox, *, transport=None, env=None, clock=utcnow, rtsp_runner=None):
        self.config = config
        self.outbox = outbox
        self.transport = transport or RequestsTransport()
        self.env = os.environ if env is None else env
        self.clock = clock
        self.rtsp_runner = rtsp_runner or self._rtsp_capture
        self.base = checked_url(env_value(self.env, config["api_base_url_env"]), {"http", "https"}, base=True)
        self.token = env_value(self.env, config["api_token_env"])
        self.devices = {d["device_id"]: d for d in config["devices"] if d.get("enabled", False)}

    def _request(self, method, url, **kwargs):
        response = self.transport.request(method, url, timeout=self.config["http_timeout_seconds"], **kwargs)
        if 300 <= response.status < 400:
            raise GatewayError("redirect_refused")
        if len(response.body) > kwargs.get("max_bytes", MAX_ASSET):
            raise GatewayError("response_too_large")
        if not 200 <= response.status < 300:
            raise GatewayError("http_status_" + str(response.status))
        return response

    def api(self, method, route, *, record=None, key=None, asset=None):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        options = {"headers": headers, "max_bytes": 2 * 1024 * 1024}
        if record is not None:
            options["body"] = encode(record)
            headers["Content-Type"] = "application/json"
        if asset is not None:
            extension = "jpg" if asset["mime"] == "image/jpeg" else "png" if asset["mime"] == "image/png" else "json"
            options["file"] = ("capture." + extension, bytes(asset["asset_bytes"]), asset["mime"])
            options["fields"] = {"source_kind": asset["source_kind"], "source_id": asset["source_id"],
                                 "public_summary": ""}
        response = self._request(method, self.base + route, **options)
        parsed = json_body(response.body)
        data = parsed.get("data")
        if not isinstance(data, dict):
            raise GatewayError("invalid_api_envelope")
        return data

    def due(self, device_id, now):
        query = urlencode({"device_id": device_id, "since": iso(now - timedelta(seconds=self.config["lookback_seconds"])),
                           "as_of": iso(now), "limit": 500, "offset": 0})
        data = self.api("GET", "/api/v1/device-captures/due?" + query)
        # Do not pick a misleading "latest" slot from a truncated oldest-first response.
        if data.get("has_more") or data.get("truncated"):
            raise GatewayError("due_window_too_dense")
        items = data.get("items")
        if not isinstance(items, list):
            raise GatewayError("invalid_due_response")
        accepted = []
        for slot in items:
            if not isinstance(slot, dict) or slot.get("device_id") != device_id:
                raise GatewayError("due_device_mismatch")
            if not re.fullmatch(r"[0-9a-f]{64}", str(slot.get("slot_id", ""))):
                raise GatewayError("invalid_slot_id")
            uuid(slot.get("policy_id"))
            moment = parse_time(slot.get("slot_at"))
            age = (now - moment).total_seconds()
            if not 0 <= age <= self.config["max_slot_age_seconds"]:
                continue
            if slot.get("priority") not in {"focus", "routine"}:
                raise GatewayError("invalid_slot_priority")
            adapter = self.devices[device_id]["adapter"]
            expected = "gate_status" if adapter == "http_gate_json" else "camera_snapshot"
            if slot.get("record_type") != expected:
                continue  # Continuous video collection is explicitly outside this MVP.
            watermark = self.outbox.watermark(device_id)
            if watermark is None or moment > watermark:
                accepted.append(slot)
        return accepted

    def _rtsp_capture(self, url, *, timeout, max_bytes):
        binary = env_value(self.env, "FFMPEG_BIN")
        path = Path(binary)
        if not path.is_absolute() or not path.is_file():
            raise GatewayError("ffmpeg_binary_not_configured")
        with tempfile.TemporaryDirectory(prefix="edge-frame-") as directory:
            output = Path(directory) / "frame.jpg"
            command = [str(path), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                       "-rtsp_transport", "tcp", "-i", url, "-frames:v", "1", "-an",
                       "-fs", str(max_bytes + 1), "-f", "image2", str(output)]
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired:
                raise GatewayError("rtsp_capture_timeout") from None
            except OSError:
                raise GatewayError("rtsp_capture_unavailable") from None
            if result.returncode or not output.is_file():
                raise GatewayError("rtsp_capture_failed")
            with output.open("rb") as stream:
                data = stream.read(max_bytes + 1)
            if not data or len(data) > max_bytes:
                raise GatewayError("response_too_large")
            return data

    def capture(self, slot, device):
        adapter = device["adapter"]
        url = checked_url(env_value(self.env, device["url_env"]),
                          {"rtsp", "rtsps"} if adapter == "rtsp_snapshot" else {"http", "https"})
        headers = {"Accept": "application/json" if adapter == "http_gate_json" else "image/jpeg,image/png"}
        if device.get("token_env"):
            headers["Authorization"] = "Bearer " + env_value(self.env, device["token_env"])
        if adapter == "rtsp_snapshot":
            raw = self.rtsp_runner(url, timeout=self.config["http_timeout_seconds"],
                                   max_bytes=self.config["max_asset_bytes"])
        else:
            raw = self._request("GET", url, headers=headers, max_bytes=self.config["max_asset_bytes"]).body
        if not raw or len(raw) > self.config["max_asset_bytes"]:
            raise GatewayError("response_too_large")
        fetched_at = self.clock()
        captured_at, basis, data = fetched_at, "fetch_time_not_verified_exposure_time", {}
        if adapter == "http_gate_json":
            payload = json_body(raw)
            no_credentials_in_receipt(payload, raw)
            data = gate_data(payload, device)
            if device.get("timestamp_field"):
                captured_at = parse_time(field_value(payload, device["timestamp_field"]))
                basis = "vendor_timestamp"
            else:
                basis = "fetch_time_not_verified_measurement_time"
            mime, source_kind = "application/json", "official_api"
        else:
            mime, source_kind = image_mime(raw), "image"
        if (captured_at < parse_time(slot["slot_at"]) - timedelta(seconds=5)
                or captured_at > fetched_at + timedelta(minutes=5)):
            raise GatewayError("source_time_outside_slot")
        record = {"device_id": slot["device_id"], "source_record_id": slot["slot_id"],
                  "record_type": slot["record_type"], "captured_at": iso(captured_at), "data": data,
                  "policy_id": slot["policy_id"], "slot_at": slot["slot_at"], "priority": slot["priority"],
                  "note": f"edge_read_only; timestamp_basis={basis}; mapping_version={device['mapping_version']}; fetched_at={iso(fetched_at)}"}
        return {"bytes": raw, "mime": mime, "source_kind": source_kind, "record": record}

    def process(self, row):
        key = row["job_key"]
        try:
            if row["device_id"] not in self.devices:
                raise GatewayError("device_disabled_in_local_configuration")
            device = self.devices[row["device_id"]]
            if row["phase"] == "capture_pending":
                if (self.clock() - parse_time(row["slot_at"])).total_seconds() > self.config["max_slot_age_seconds"]:
                    self.outbox.expired(key)
                    return "expired_no_capture"
                self.outbox.reserve_check(self.config["max_asset_bytes"], self.config["max_pending_bytes"])
                captured = self.capture(json.loads(row["slot_json"]), device)
                self.outbox.store_capture(key, captured, device["source_id"], self.config["max_pending_bytes"])
                row = self.outbox.row(key)
            if row["phase"] == "asset_pending":
                received = self.api("POST", "/api/v1/ingestion/assets", key=row["asset_key"], asset=row)
                self.outbox.asset_received(key, received.get("id"))
                row = self.outbox.row(key)
            if row["phase"] == "record_pending":
                received = self.api("POST", "/api/v1/device-records", record=json.loads(row["record_json"]),
                                    key=row["record_key"])
                if not received.get("id"):
                    raise GatewayError("invalid_device_record_receipt")
                self.outbox.delivered(key, self.clock())
            return "delivered"
        except GatewayError as error:
            self.outbox.failed(key, error.code, self.clock(), self.config["retry_base_seconds"])
            return error.code

    def run_once(self):
        report = {"mode": "read_only", "delivered": 0, "pending_or_failed": 0,
                  "expired_without_capture": 0, "new_jobs": 0, "errors": [],
                  "control_supported": False, "field_connectivity_verified": False}
        def record_result(result):
            if result == "delivered":
                report["delivered"] += 1
            elif result == "expired_no_capture":
                report["expired_without_capture"] += 1
            else:
                report["pending_or_failed"] += 1
                report["errors"].append(result)
        for row in self.outbox.ready(self.clock(), self.config["max_jobs_per_pass"]):
            record_result(self.process(row))
        selections = []
        for device_id in self.devices:
            if self.outbox.busy(device_id):
                continue
            try:
                slots = self.due(device_id, self.clock())
                if not slots:
                    continue
                # At most one new sample per device per pass; never replay a backlog of old frames.
                chosen = sorted(slots, key=lambda s: (s["priority"] == "focus", parse_time(s["slot_at"])),
                                reverse=True)[0]
                watermark = max(parse_time(s["slot_at"]) for s in slots)
                selections.append((chosen, watermark))
            except GatewayError as error:
                report["errors"].append(error.code)
        selections.sort(key=lambda pair: (pair[0]["priority"] != "focus", pair[0]["slot_at"]))
        for slot, watermark in selections[:self.config["max_jobs_per_pass"]]:
            try:
                row = self.outbox.enqueue(slot, watermark, self.clock(), self.config["max_pending_jobs"])
                report["new_jobs"] += 1
                record_result(self.process(row))
            except GatewayError as error:
                report["errors"].append(error.code)
        report["errors"] = sorted(set(report["errors"]))
        return report


class ProcessLock:
    """An OS advisory lock only for this collector's local outbox, released on exit/crash."""
    def __init__(self, path):
        self.path, self.stream = path, None

    def __enter__(self):
        self.stream = self.path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise GatewayError("gateway_already_running_for_outbox") from None
        return self

    def __exit__(self, *_):
        if self.stream:
            self.stream.close()
            self.stream = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--once", action="store_true")
    action.add_argument("--loop", action="store_true")
    action.add_argument("--validate", action="store_true", help="validate config shape only; do not read URL/token values or make requests")
    args = parser.parse_args(argv)
    outbox = None
    lock = None
    try:
        config = validate_config(json.loads(args.config.read_text(encoding="utf-8")))
        if args.validate:
            print(json.dumps({"configuration": "valid", "configured_devices": len(config["devices"]),
                              "enabled_devices": sum(d.get("enabled", False) for d in config["devices"]),
                              "network_called": False}, ensure_ascii=False))
            return 0
        directory = Path(config["state_directory"])
        directory.mkdir(parents=True, exist_ok=True)
        lock = ProcessLock(directory / "gateway.lock")
        lock.__enter__()
        outbox = Outbox(directory / "outbox.sqlite")
        gateway = Gateway(config, outbox)
        while True:
            print(json.dumps(gateway.run_once(), ensure_ascii=False), flush=True)
            if args.once:
                return 0
            time.sleep(config["poll_seconds"])
    except KeyboardInterrupt:
        return 130
    except (GatewayError, OSError, json.JSONDecodeError, sqlite3.Error) as error:
        code = error.code if isinstance(error, GatewayError) else "local_configuration_or_state_error"
        print(json.dumps({"error": code, "secrets_logged": False}), file=sys.stderr)
        return 1
    finally:
        if outbox:
            outbox.close()
        if lock:
            lock.__exit__()


if __name__ == "__main__":
    raise SystemExit(main())
