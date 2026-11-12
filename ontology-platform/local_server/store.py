"""PostgreSQL jobs, fenced worker leases and atomic release publication.

Construction and read operations never initialize tables. Only an explicit
admin ``ensure_schema`` creates the control schema or grants privileges.
Every worker mutation locks its job and checks the database clock and fencing
token in the same transaction as the mutation.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import contained_path


class LeaseLost(RuntimeError):
    """The worker no longer owns an unexpired lease for this attempt."""


class StoreUnavailable(RuntimeError):
    """Sanitized connection failure, without libpq connection parameters."""


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _job(row: dict | None) -> dict | None:
    if row is None:
        return None
    value = _json_value(dict(row))
    value["job_id"] = value["id"]
    return value


def _release(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = _json_value(dict(row))
    value = dict(row["metadata"])
    value.update(row)
    value["release_id"] = row["id"]
    return value


def _uuid(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("identifier must be a UUID") from None


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    # Serialize here to reject nonportable types and NaN before opening a DB tx.
    return json.loads(json.dumps(value, allow_nan=False))


class Store:
    def __init__(self, config, role: str = "api"):
        if role not in ("admin", "api", "worker"):
            raise ValueError("role must be admin, api or worker")
        self.config = config
        self.role = role

    def dsn(self, role: str | None = None) -> str:
        role = self.role if role is None else role
        if role not in ("admin", "api", "worker"):
            raise ValueError("unknown SQL role")
        return self.config.sql[role + "_dsn"]

    def connect(self):
        try:
            return psycopg.connect(self.dsn(), row_factory=dict_row, connect_timeout=5, application_name="lzo-local-" + self.role)
        except (psycopg.Error, ValueError):
            # Chaining libpq's exception can expose its conninfo stack locals in
            # test runners and diagnostic renderers, even if its message is safe.
            raise StoreUnavailable("SQL connection unavailable") from None

    def _writer(self):
        if self.role not in ("admin", "worker"):
            raise PermissionError("operation requires the worker or administrator role")

    def _relative(self, value, root=None) -> str:
        root = Path(self.config.data_dir if root is None else root).resolve()
        return contained_path(root, value).relative_to(root).as_posix()

    def _release_metadata(self, metadata: dict) -> dict:
        """Normalize declared artifact references, never business/provenance data."""
        details = _object(metadata, "release metadata")
        legacy = details.get("legacy_snapshot") is True
        base = details.get("path_base", "review" if legacy else "data")
        if base not in ("data", "review") or (base == "review" and not legacy):
            raise ValueError("release path_base conflicts with its snapshot type")
        root = self.config.review_dir if base == "review" else self.config.data_dir
        details["path_base"] = base
        for name in ("navigation_dir", "manifest_path"):
            if name in details:
                details[name] = self._relative(details[name], root)
        if "source_path" in details:
            details["source_path"] = self._relative(details["source_path"])
        navigation = details.get("navigation")
        if navigation is not None:
            if not isinstance(navigation, dict):
                raise ValueError("navigation must be an object")
            for name in ("data_dir", "manifest_path", "manifest"):
                if name in navigation and isinstance(navigation[name], str):
                    navigation[name] = self._relative(navigation[name], root)
        return details

    def ensure_schema(self) -> None:
        if self.role != "admin":
            raise PermissionError("schema initialization requires the administrator role")
        api_role = conninfo_to_dict(self.dsn("api")).get("user")
        worker_role = conninfo_to_dict(self.dsn("worker")).get("user")
        if not api_role or not worker_role or api_role == worker_role:
            raise ValueError("API and worker DSNs require distinct explicit SQL users")
        with self.connect() as conn:
            identity = conn.execute("SELECT current_user AS username, current_database() AS database").fetchone()
            if identity["username"] in (api_role, worker_role):
                raise ValueError("administrator must be separate from API and worker")
            conn.execute("CREATE SCHEMA IF NOT EXISTS lzo_local")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lzo_local.jobs (
                    id uuid PRIMARY KEY,
                    source_path text NOT NULL,
                    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
                    mapping_sha256 text NOT NULL CHECK (mapping_sha256 ~ '^[a-f0-9]{64}$'),
                    schema_version text NOT NULL,
                    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','failed','succeeded')),
                    stage text NOT NULL DEFAULT 'queued',
                    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                    progress jsonb NOT NULL DEFAULT '{}'::jsonb,
                    error jsonb,
                    result jsonb,
                    worker_id text,
                    lease_token bigint NOT NULL DEFAULT 0,
                    lease_expires_at timestamptz,
                    attempts integer NOT NULL DEFAULT 0,
                    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                    UNIQUE(source_sha256, mapping_sha256, schema_version)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_claim_idx ON lzo_local.jobs(status,created_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lzo_local.releases (
                    id uuid PRIMARY KEY,
                    job_id uuid REFERENCES lzo_local.jobs(id),
                    lease_token bigint,
                    metadata jsonb NOT NULL,
                    status text NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','published')),
                    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                    published_at timestamptz
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lzo_local.state (
                    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
                    active_release_id uuid REFERENCES lzo_local.releases(id),
                    deployment_id uuid NOT NULL,
                    schema_version text NOT NULL DEFAULT '1',
                    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
                )
            """)
            conn.execute("INSERT INTO lzo_local.state(singleton,deployment_id) VALUES (true,%s) ON CONFLICT DO NOTHING", (uuid4(),))
            if conn.execute("SELECT schema_version FROM lzo_local.state WHERE singleton").fetchone()["schema_version"] != "1":
                raise ValueError("unsupported control schema version")
            conn.execute("REVOKE ALL ON SCHEMA lzo_local FROM PUBLIC")
            conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA lzo_local FROM PUBLIC")
            for role in (api_role, worker_role):
                # A restored database can revoke PUBLIC CONNECT. Service roles
                # need this explicit database privilege as well as schema grants.
                conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(identity["database"]), sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT USAGE ON SCHEMA lzo_local TO {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA lzo_local FROM {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT SELECT ON lzo_local.jobs,lzo_local.releases,lzo_local.state TO {}").format(sql.Identifier(role)))
            conn.execute(sql.SQL("GRANT INSERT (id,source_path,source_sha256,mapping_sha256,schema_version,metadata) ON lzo_local.jobs TO {}").format(sql.Identifier(api_role)))
            conn.execute(sql.SQL("GRANT INSERT,UPDATE ON lzo_local.jobs,lzo_local.releases TO {}").format(sql.Identifier(worker_role)))
            conn.execute(sql.SQL("GRANT UPDATE (active_release_id,updated_at) ON lzo_local.state TO {}").format(sql.Identifier(worker_role)))
            conn.execute(sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(sql.Identifier(identity["database"]), sql.Identifier(worker_role)))
            # Fresh databases may otherwise grant CREATE on public to all users.
            conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

    def submit_job(self, source_path, source_sha256: str, mapping_sha256: str, *, schema_version: str | None = None, metadata: dict | None = None) -> dict:
        path = contained_path(self.config.data_dir, source_path)
        if not path.is_file():
            raise ValueError("source must be an existing private data file")
        for name, value in (("source_sha256", source_sha256), ("mapping_sha256", mapping_sha256)):
            if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
                raise ValueError(name + " must be a lowercase SHA256 digest")
        version = str(self.config.schema_version if schema_version is None else schema_version)
        if not version or len(version) > 64:
            raise ValueError("invalid schema version")
        details = _object({} if metadata is None else metadata, "metadata")
        with self.connect() as conn:
            row = conn.execute("""
                INSERT INTO lzo_local.jobs(id,source_path,source_sha256,mapping_sha256,schema_version,metadata)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_sha256,mapping_sha256,schema_version) DO NOTHING RETURNING *
            """, (uuid4(), self._relative(path), source_sha256, mapping_sha256, version, Jsonb(details))).fetchone()
            if row is None:
                row = conn.execute("SELECT * FROM lzo_local.jobs WHERE source_sha256=%s AND mapping_sha256=%s AND schema_version=%s", (source_sha256, mapping_sha256, version)).fetchone()
            return _job(row)

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as conn:
            return _job(conn.execute("SELECT * FROM lzo_local.jobs WHERE id=%s", (_uuid(job_id),)).fetchone())

    def list_jobs(self, limit: int = 100, offset: int = 0) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000 or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid job page")
        with self.connect() as conn:
            return [_job(row) for row in conn.execute("SELECT * FROM lzo_local.jobs ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s", (limit, offset)).fetchall()]

    def _seconds(self, lease_seconds: int | None) -> int:
        seconds = self.config.limits.get("lease_seconds", 120) if lease_seconds is None else lease_seconds
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 86400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        return seconds

    def claim_job(self, worker_id: str, *, lease_seconds: int | None = None) -> dict | None:
        self._writer()
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 200:
            raise ValueError("worker_id must be a nonempty identifier")
        seconds = self._seconds(lease_seconds)
        with self.connect() as conn:
            # Claim decisions must serialize across processes, including when
            # different queued jobs exist. The first version runs one import.
            conn.execute("SELECT pg_advisory_xact_lock(5498699462566530892)")
            if conn.execute("SELECT 1 FROM lzo_local.jobs WHERE status='running' AND lease_expires_at>clock_timestamp() LIMIT 1").fetchone():
                return None
            row = conn.execute("""
                WITH candidate AS (
                    SELECT id FROM lzo_local.jobs
                    WHERE status='queued' OR (status='running' AND lease_expires_at<=clock_timestamp())
                    ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE lzo_local.jobs j SET status='running',worker_id=%s,
                    lease_token=j.lease_token+1,attempts=j.attempts+1,
                    lease_expires_at=clock_timestamp()+make_interval(secs => %s),
                    error=NULL,updated_at=clock_timestamp()
                FROM candidate WHERE j.id=candidate.id RETURNING j.*
            """, (worker_id, seconds)).fetchone()
            return _job(row)

    @staticmethod
    def _locked_lease(conn, job_id, worker_id, lease_token):
        if isinstance(lease_token, bool) or not isinstance(lease_token, int) or lease_token < 1:
            raise LeaseLost("worker lease is absent, expired or superseded")
        row = conn.execute("""
            SELECT * FROM lzo_local.jobs WHERE id=%s AND status='running'
              AND worker_id=%s AND lease_token=%s AND lease_expires_at>clock_timestamp()
            FOR UPDATE
        """, (_uuid(job_id), worker_id, lease_token)).fetchone()
        if row is None:
            raise LeaseLost("worker lease is absent, expired or superseded")
        return row

    def check_lease(self, job_id, worker_id, lease_token) -> bool:
        try:
            with self.connect() as conn:
                self._locked_lease(conn, job_id, worker_id, lease_token)
                return True
        except LeaseLost:
            return False

    def heartbeat(self, job_id, worker_id, lease_token, *, stage: str | None = None, progress: dict | None = None, lease_seconds: int | None = None) -> dict:
        self._writer()
        seconds = self._seconds(lease_seconds)
        if stage is not None and (not isinstance(stage, str) or not stage or len(stage) > 64):
            raise ValueError("stage must be a nonempty label of at most 64 characters")
        progress = None if progress is None else _object(progress, "progress")
        with self.connect() as conn:
            self._locked_lease(conn, job_id, worker_id, lease_token)
            row = conn.execute("""
                UPDATE lzo_local.jobs SET stage=COALESCE(%s,stage),progress=COALESCE(%s,progress),
                    lease_expires_at=clock_timestamp()+make_interval(secs => %s),updated_at=clock_timestamp()
                WHERE id=%s RETURNING *
            """, (stage, None if progress is None else Jsonb(progress), seconds, _uuid(job_id))).fetchone()
            return _job(row)

    def fail_job(self, job_id, worker_id, lease_token, error, *, retryable: bool = False) -> dict:
        self._writer()
        if isinstance(error, str):
            error = {"code": "IMPORT_FAILED", "message": error}
        details = _object(error, "error")
        details["retryable"] = bool(retryable)
        with self.connect() as conn:
            self._locked_lease(conn, job_id, worker_id, lease_token)
            return _job(conn.execute("UPDATE lzo_local.jobs SET status='failed',error=%s,lease_expires_at=NULL,updated_at=clock_timestamp() WHERE id=%s RETURNING *", (Jsonb(details), _uuid(job_id))).fetchone())

    def finish_job(self, job_id, worker_id, lease_token, result: dict | None = None) -> dict:
        self._writer()
        details = _object({} if result is None else result, "result")
        with self.connect() as conn:
            self._locked_lease(conn, job_id, worker_id, lease_token)
            return _job(conn.execute("UPDATE lzo_local.jobs SET status='succeeded',stage='complete',result=%s,lease_expires_at=NULL,updated_at=clock_timestamp() WHERE id=%s RETURNING *", (Jsonb(details), _uuid(job_id))).fetchone())

    def retry_job(self, job_id) -> dict:
        self._writer()
        with self.connect() as conn:
            row = conn.execute("UPDATE lzo_local.jobs SET status='queued',stage='queued',worker_id=NULL,lease_expires_at=NULL,updated_at=clock_timestamp() WHERE id=%s AND status='failed' RETURNING *", (_uuid(job_id),)).fetchone()
            if row is None:
                raise ValueError("only failed jobs can be retried")
            return _job(row)

    def register_release(self, metadata: dict, *, job_id=None, worker_id=None, lease_token=None) -> dict:
        self._writer()
        details = self._release_metadata(metadata)
        release_id = _uuid(details.pop("release_id", details.pop("id", str(uuid4()))))
        if job_id is None and (self.role != "admin" or worker_id is not None or lease_token is not None):
            raise PermissionError("worker release registration requires a job lease")
        with self.connect() as conn:
            if job_id is not None:
                self._locked_lease(conn, job_id, worker_id, lease_token)
            row = conn.execute("""
                INSERT INTO lzo_local.releases(id,job_id,lease_token,metadata) VALUES (%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING RETURNING *
            """, (release_id, None if job_id is None else _uuid(job_id), lease_token, Jsonb(details))).fetchone()
            if row is None:
                row = conn.execute("SELECT * FROM lzo_local.releases WHERE id=%s", (release_id,)).fetchone()
                existing_job_id = None if row["job_id"] is None else str(row["job_id"])
                if row["metadata"] != details or existing_job_id != (None if job_id is None else _uuid(job_id)) or row["lease_token"] != lease_token:
                    # Immutable release IDs must not be reused for a new attempt.
                    raise ValueError("release identifier is already registered with different content or lease")
            return _release(row)

    def get_release(self, release_id) -> dict | None:
        with self.connect() as conn:
            return _release(conn.execute("SELECT * FROM lzo_local.releases WHERE id=%s", (_uuid(release_id),)).fetchone())

    def list_releases(self, limit: int = 100, offset: int = 0) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000 or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid release page")
        with self.connect() as conn:
            return [_release(row) for row in conn.execute("SELECT * FROM lzo_local.releases ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s", (limit, offset)).fetchall()]

    def active_release(self) -> dict | None:
        with self.connect() as conn:
            return _release(conn.execute("SELECT r.* FROM lzo_local.state s JOIN lzo_local.releases r ON r.id=s.active_release_id WHERE s.singleton").fetchone())

    def publish_release(self, release_id, *, job_id=None, worker_id=None, lease_token=None) -> dict:
        self._writer()
        release_id = _uuid(release_id)
        if job_id is None and (self.role != "admin" or worker_id is not None or lease_token is not None):
            raise PermissionError("worker publication requires a job lease")
        with self.connect() as conn:
            # Serialize publications so readers observe exactly one whole release.
            conn.execute("SELECT singleton FROM lzo_local.state WHERE singleton FOR UPDATE").fetchone()
            if job_id is not None:
                self._locked_lease(conn, job_id, worker_id, lease_token)
            row = conn.execute("SELECT * FROM lzo_local.releases WHERE id=%s FOR UPDATE", (release_id,)).fetchone()
            if row is None:
                raise ValueError("release is not registered")
            if job_id is not None and (str(row["job_id"]) != _uuid(job_id) or row["lease_token"] != lease_token):
                raise LeaseLost("release belongs to a different worker attempt")
            if job_id is None and row["job_id"] is not None:
                raise PermissionError("job releases require their live worker lease")
            # Recheck using the current DB clock immediately before publication.
            if job_id is not None:
                self._locked_lease(conn, job_id, worker_id, lease_token)
            row = conn.execute("UPDATE lzo_local.releases SET status='published',published_at=COALESCE(published_at,clock_timestamp()) WHERE id=%s RETURNING *", (release_id,)).fetchone()
            if job_id is None:
                conn.execute("UPDATE lzo_local.state SET active_release_id=%s,updated_at=clock_timestamp() WHERE singleton", (release_id,))
            else:
                activated = conn.execute("""
                    UPDATE lzo_local.state SET active_release_id=%s,updated_at=clock_timestamp()
                    WHERE singleton AND EXISTS (
                        SELECT 1 FROM lzo_local.jobs WHERE id=%s AND status='running'
                          AND worker_id=%s AND lease_token=%s AND lease_expires_at>clock_timestamp()
                    ) RETURNING singleton
                """, (release_id, _uuid(job_id), worker_id, lease_token)).fetchone()
                if activated is None:
                    raise LeaseLost("worker lease expired before activation")
            return _release(row)
