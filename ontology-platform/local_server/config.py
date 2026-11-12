"""Validated, explicit service targets and private storage boundaries.

Configuration paths are relative to the configuration file. Mapping and review
paths are relative to the configured source root. Loading never contacts a
service, creates a directory, or prints a credential.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from psycopg.conninfo import conninfo_to_dict


class ConfigError(ValueError):
    """Invalid configuration (messages never include a DSN or token)."""


def contained_path(root: Path, *parts: str | Path) -> Path:
    """Resolve a child path, rejecting traversal and symlink/junction escapes."""
    if any(not isinstance(part, (str, Path)) or (isinstance(part, str) and (not part or "\x00" in part)) for part in parts):
        raise ConfigError("path components must be nonempty paths")
    try:
        root = Path(root).resolve()
        candidate = root.joinpath(*parts).resolve()
    except (OSError, ValueError, TypeError, RuntimeError):
        raise ConfigError("path cannot be safely resolved") from None
    if not candidate.is_relative_to(root):
        raise ConfigError("path escapes its configured root")
    return candidate


def _mapping(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be an object")
    return dict(value)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _resolve(base: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ConfigError(f"{name} must be a nonempty path")
    return (base / value).resolve()


def _http_target(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError("Fuseki target must be an explicit HTTP dataset URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError()
        if not parsed.path.strip("/") or any(part in (".", "..") for part in parsed.path.split("/")):
            raise ValueError()
        host = parsed.hostname.lower()
        authority = f"[{host}]" if ":" in host else host
        if port is not None:
            authority += f":{port}"
        return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/"), "", ""))
    except (TypeError, ValueError):
        raise ConfigError("Fuseki target must be an explicit HTTP dataset URL") from None


@dataclass(frozen=True)
class Config:
    root: Path
    data_dir: Path
    review_dir: Path
    mapping_file: Path
    host: str
    port: int
    sql: dict = field(repr=False)
    fuseki_url: str = field(repr=False)
    limits: dict
    backup: dict = field(repr=False)
    runtime: dict = field(repr=False)
    schema_version: str = "1"
    write_token: str = field(default="", repr=False)
    allowed_hosts: tuple[str, ...] = ()
    config_path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        config_path = Path(path).resolve()
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ConfigError("configuration cannot be read as JSON") from None
        payload = _mapping(payload, "configuration")
        base = config_path.parent
        root = _resolve(base, payload.get("root", ".."), "root")
        data_dir = _resolve(base, payload.get("data_dir", "../.runtime/local-server"), "data_dir")
        if root == data_dir or root.is_relative_to(data_dir):
            raise ConfigError("data_dir must not contain the source root")
        mapping_file = contained_path(root, payload.get("mapping_file", "config/local-server-mapping.json"))
        review_dir = _resolve(root, payload.get("review_dir", "docs/fish/ontology-review"), "review_dir")
        host = payload.get("host", "127.0.0.1")
        if isinstance(host,str) and ":" in host:
            raise ConfigError("IPv6 bind is not supported by this IPv4 release")
        # Non-loopback service exposure requires an explicit operator choice.
        if not isinstance(host, str) or not host or (host not in ("127.0.0.1", "localhost") and payload.get("allow_remote_bind") is not True):
            raise ConfigError("remote host requires allow_remote_bind=true")
        port = _positive_int(payload.get("port", 8792), "port")
        if port > 65535:
            raise ConfigError("port must be at most 65535")
        sql_config = _mapping(payload.get("sql", {}), "sql")
        allowed = sql_config.get("allowed_targets")
        if not isinstance(allowed, list) or not allowed:
            raise ConfigError("sql.allowed_targets must explicitly list permitted targets")
        targets = set()
        for target in allowed:
            target = _mapping(target, "sql target")
            target_host = target.get("host")
            target_db = target.get("database")
            target_port = _positive_int(target.get("port"), "SQL target port")
            if target_port > 65535 or not isinstance(target_host, str) or not target_host or not isinstance(target_db, str) or not target_db or "," in target_host:
                raise ConfigError("SQL allowlist requires host, port and database")
            targets.add((target_host.lower(), str(target_port), target_db))
        for role in ("admin", "api", "worker"):
            key = role + "_dsn"
            env_key = sql_config.get(key + "_env")
            value = sql_config.get(key)
            if env_key:
                if not isinstance(env_key, str):
                    raise ConfigError(f"sql.{key}_env must be an environment variable name")
                value = os.environ.get(env_key)
            elif isinstance(value, str) and re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", value):
                value = os.environ.get(value[2:-1])
            if not isinstance(value, str) or not value:
                raise ConfigError(f"SQL {role} connection environment variable is missing")
            try:
                parsed = conninfo_to_dict(value)
                actual = (parsed.get("host", "").lower(), parsed.get("port", ""), parsed.get("dbname", ""))
                if actual not in targets or parsed.get("service") or (parsed.get("hostaddr") and parsed["hostaddr"] != parsed.get("host")):
                    raise ValueError()
            except Exception:
                raise ConfigError(f"SQL {role} target is invalid or not explicitly allowed") from None
            sql_config[key] = value
        fuseki_url = _http_target(payload.get("fuseki_url", "http://127.0.0.1:23059/fish_l1"))
        fuseki_allowed = payload.get("fuseki_allowed_targets")
        if not isinstance(fuseki_allowed, list) or not fuseki_allowed or fuseki_url not in {_http_target(url) for url in fuseki_allowed}:
            raise ConfigError("Fuseki target is not explicitly allowed")
        limits = {"upload_bytes": 64 * 1024 * 1024, "page_size": 100, "max_page_size": 1000, "query_timeout_seconds": 15, "min_free_disk_bytes": 1024 * 1024 * 1024, "lease_seconds": 120, "worker_poll_seconds": 1}
        limits.update(_mapping(payload.get("limits", payload.get("limit", {})), "limits"))
        for key, value in limits.items():
            _positive_int(value, f"limits.{key}")
        if limits["page_size"] > limits["max_page_size"]:
            raise ConfigError("page_size exceeds max_page_size")
        runtime = _mapping(payload.get("runtime", {}), "runtime")
        if "directory" in runtime:
            contained_path(data_dir, runtime["directory"])
        backup = _mapping(payload.get("backup", {}), "backup")
        auth = _mapping(payload.get("auth", {}), "auth")
        token_env = auth.get("write_token_env", payload.get("write_token_env", "LZO_LOCAL_WRITE_TOKEN"))
        if not isinstance(token_env, str):
            raise ConfigError("write_token_env must be an environment variable name")
        write_token = os.environ.get(token_env, "")
        schema_version = str(payload.get("schema_version", "1"))
        if not schema_version or len(schema_version) > 64:
            raise ConfigError("schema_version must be nonempty and at most 64 characters")
        allowed_hosts = payload.get("allowed_hosts", [f"127.0.0.1:{port}", f"localhost:{port}"])
        if not isinstance(allowed_hosts, list) or not all(isinstance(value, str) and value for value in allowed_hosts):
            raise ConfigError("allowed_hosts must be a nonempty string list")
        return cls(root=root, data_dir=data_dir, review_dir=review_dir, mapping_file=mapping_file, host=host, port=port, sql=sql_config, fuseki_url=fuseki_url, limits=limits, backup=backup, runtime=runtime, schema_version=schema_version, write_token=write_token, allowed_hosts=tuple(allowed_hosts), config_path=config_path)

    @property
    def data_root(self) -> Path:
        return self.data_dir

    @property
    def runtime_dir(self) -> Path:
        return self.data_path(self.runtime.get("directory", "runtime"))

    @property
    def runtime_root(self) -> Path:
        return self.runtime_dir

    @property
    def limit(self) -> dict:
        return self.limits

    @property
    def token(self) -> str:
        return self.write_token

    def data_path(self, *parts: str | Path) -> Path:
        return contained_path(self.data_dir, *parts)
