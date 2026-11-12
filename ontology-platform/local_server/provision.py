"""Create one fresh, private native deployment without touching existing data.

Provisioning creates empty databases, not application tables. Restore a reviewed
backup before running the explicit CLI ``init`` operation. Tool installations are
read only. An interrupted or failed directory is never initialized a second time.
"""
from __future__ import annotations

import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .config import Config
from .lifecycle import NativeServices, LifecycleError, atomic_json


DATABASES = ("lzo", "lzo_gis", "lzo_timeseries", "lzo_catalog")
ROLES = {"admin": "lzo_local_admin", "api": "lzo_local_api", "worker": "lzo_local_worker"}
SQL_ENV = {role: "LZO_LOCAL_" + role.upper() + "_DATABASE_URL" for role in ROLES}


class ProvisionError(ValueError):
    """Only a safe operation code may cross the command boundary."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _unlinked_absolute(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ProvisionError("DATA_LINK_REJECTED")
    return path


def _fresh_target(root, data_dir, allow_external):
    root = _unlinked_absolute(root)
    data = _unlinked_absolute(data_dir)
    if data == Path(data.anchor) or data == root or root.is_relative_to(data):
        raise ProvisionError("DATA_OUTSIDE_WORKSPACE")
    if not allow_external and not data.is_relative_to(root / ".runtime"):
        raise ProvisionError("DATA_OUTSIDE_WORKSPACE")
    if data == root / ".runtime":
        raise ProvisionError("DATA_OUTSIDE_WORKSPACE")
    if not (root / "scripts" / "run_local_server.py").is_file() or not (root / "config" / "local-server-mapping.json").is_file() or not (root / "infra" / "local-server" / "LocalFusekiRunner.java").is_file():
        raise ProvisionError("SOURCE_ROOT_NOT_AVAILABLE")
    if data.exists() and (not data.is_dir() or any(data.iterdir())):
        raise ProvisionError("DATA_NOT_EMPTY")
    return root, data


def _check_ports(ports):
    if any(isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535 or port in (25449, 23049) for port in ports) or len(set(ports)) != len(ports):
        raise ProvisionError("PORT_REJECTED")
    probes = []
    try:
        for port in ports:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probes.append(probe)
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
    except OSError:
        raise ProvisionError("PORT_IN_USE") from None
    finally:
        for probe in probes:
            probe.close()


def _run(command, code, *, timeout=30):
    try:
        result = subprocess.run([str(value) for value in command], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        raise ProvisionError(code) from None
    if result.returncode:
        raise ProvisionError(code)
    return result.stdout.decode("utf-8", errors="replace")


def _tools(pg_bin, java_home, fuseki_home, data):
    pg, java, fuseki = (Path(value).resolve() for value in (pg_bin, java_home, fuseki_home))
    suffix = ".exe" if os.name == "nt" else ""
    required = [pg / (name + suffix) for name in ("initdb", "pg_ctl", "postgres", "pg_dump", "pg_restore")]
    required += [java / "bin" / ("java" + suffix), fuseki / "fuseki-server.jar"]
    if any(not path.is_file() for path in required):
        raise ProvisionError("TOOLS_NOT_AVAILABLE")
    if any(path.is_relative_to(data) or data.is_relative_to(path) for path in (pg, java, fuseki)):
        raise ProvisionError("TOOLS_OVERLAP_DATA")
    if not re.search(r"PostgreSQL\) 17(?:\.|\s|$)", _run([pg / ("postgres" + suffix), "--version"], "POSTGRES_VERSION_REJECTED")):
        raise ProvisionError("POSTGRES_VERSION_REJECTED")
    if not re.search(r'version "21(?:\.|"|-)', _run([java / "bin" / ("java" + suffix), "-version"], "JAVA_VERSION_REJECTED")):
        raise ProvisionError("JAVA_VERSION_REJECTED")
    modules = _run([java / "bin" / ("java" + suffix), "--list-modules"], "JAVA_COMPILER_REQUIRED")
    if not re.search(r"(?m)^jdk\.compiler(?:@|$)", modules):
        raise ProvisionError("JAVA_COMPILER_REQUIRED")
    if not re.search(r"\b6\.2\.\d+\b", _run([java / "bin" / ("java" + suffix), "-jar", fuseki / "fuseki-server.jar", "--version"], "FUSEKI_VERSION_REJECTED", timeout=60)):
        raise ProvisionError("FUSEKI_VERSION_REJECTED")
    return pg, java, fuseki


def _private_directory(path):
    if os.name == "nt":
        identity = _run(["whoami", "/user", "/fo", "csv", "/nh"], "PRIVATE_PERMISSIONS_FAILED")
        try:
            sid = next(csv.reader(identity.strip().splitlines()))[1]
            if not re.fullmatch(r"S-1-(?:\d+-)+\d+", sid):
                raise ValueError()
        except (ValueError, IndexError, StopIteration):
            raise ProvisionError("PRIVATE_PERMISSIONS_FAILED") from None
        _run(["icacls", path, "/inheritance:r", "/grant:r", "*" + sid + ":(OI)(CI)F"], "PRIVATE_PERMISSIONS_FAILED")
    else:
        path.chmod(0o700)


def _write_private(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _empty_databases(config, passwords):
    # All secrets stay inside libpq connection memory and protocol parameters;
    # neither shell arguments nor command output contains a password or DSN.
    with psycopg.connect(config.sql["admin_dsn"], dbname="postgres", autocommit=True, connect_timeout=10) as connection:
        for role in ("api", "worker"):
            connection.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(sql.Identifier(ROLES[role]), sql.Literal(passwords[role])))
        for database in DATABASES:
            connection.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(database), sql.Identifier(ROLES["admin"])))
            connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
            connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {},{}").format(sql.Identifier(database), sql.Identifier(ROLES["api"]), sql.Identifier(ROLES["worker"])))
    for database in DATABASES:
        with psycopg.connect(config.sql["admin_dsn"], dbname=database, connect_timeout=10) as connection:
            connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")


def provision_fresh(root, data_dir, pg_bin, java_home, fuseki_home, pg_port=25459, fuseki_port=23059, http_port=8792, *, allow_external_data_dir=False):
    """Create a fresh deployment and leave PostgreSQL and Fuseki stopped.

    DATA defaults to a child of ROOT/.runtime; a separate data disk requires
    explicit ``allow_external_data_dir=True``. Failures retain a nonsecret state
    record and are never retried destructively. Existing directories must be
    entirely empty, including hidden files. No source credentials are reused.
    """
    root, data = _fresh_target(root, data_dir, allow_external_data_dir)
    _check_ports((pg_port, fuseki_port, http_port))
    pg, java, fuseki = _tools(pg_bin, java_home, fuseki_home, data)
    deployment_id = str(uuid4())
    data.mkdir(parents=True, exist_ok=True)
    # An exclusive claim closes the race between two simultaneous provisioners.
    claim = data / ".provision.lock"
    try:
        _write_private(claim, deployment_id)
    except FileExistsError:
        raise ProvisionError("DATA_NOT_EMPTY") from None
    if sorted(path.name for path in data.iterdir()) != [claim.name]:
        claim.unlink()
        raise ProvisionError("DATA_NOT_EMPTY")
    stage = "private-permissions"
    native = None
    pwfile = data / "initdb.pwfile"
    config_path = data / "config.json"
    try:
        _private_directory(data)
        deployment = {"format": "local-server-deployment/1", "deployment_id": deployment_id,
            "root": str(root), "data_dir": str(data), "pg_port": pg_port, "fuseki_port": fuseki_port, "http_port": http_port}
        atomic_json(data / "deployment.json", deployment)
        stage = "initdb"
        atomic_json(data / "provision-state.json", {"status": "provisioning", "stage": stage, "deployment_id": deployment_id})
        passwords = {role: secrets.token_urlsafe(36) for role in ROLES}
        connections = {role: make_conninfo(host="127.0.0.1", port=pg_port, dbname="lzo_gis", user=ROLES[role], password=passwords[role]) for role in ROLES}
        environment = {SQL_ENV[role]: value for role, value in connections.items()}
        environment.update({"LZO_LOCAL_" + database.upper() + "_DATABASE_URL": make_conninfo(host="127.0.0.1", port=pg_port, dbname=database, user=ROLES["admin"], password=passwords["admin"]) for database in DATABASES})
        environment["LZO_LOCAL_WRITE_TOKEN"] = secrets.token_urlsafe(48)
        _write_private(data / "private.env", "# Private: do not upload or include in backups.\n" + "".join(key + "='" + value + "'\n" for key, value in environment.items()))
        runtime = {"directory": "runtime", "managed_postgres": True, "managed_fuseki": True,
            "pg_data_dir": "postgres/data", "pg_bin": str(pg), "pg_port": pg_port,
            "fuseki_state_dir": "fuseki", "java_home": str(java), "fuseki_home": str(fuseki), "fuseki_port": fuseki_port}
        endpoint = f"http://127.0.0.1:{fuseki_port}/fish_l1"
        payload = {"root": str(root), "data_dir": str(data), "env_file": "private.env",
            "review_dir": "docs/fish/ontology-review", "mapping_file": "config/local-server-mapping.json",
            "host": "127.0.0.1", "port": http_port, "sql": {**{role + "_dsn_env": key for role, key in SQL_ENV.items()},
                "allowed_targets": [{"host": "127.0.0.1", "port": pg_port, "database": database} for database in DATABASES]},
            "fuseki_url": endpoint, "fuseki_allowed_targets": [endpoint], "auth": {"write_token_env": "LZO_LOCAL_WRITE_TOKEN"},
            "runtime": runtime, "schema_version": "1", "backup": {}}
        atomic_json(config_path, payload)
        rdf_dir = data / "fuseki"
        rdf_dir.mkdir()
        _write_private(rdf_dir / "config.ttl", '@prefix fuseki: <http://jena.apache.org/fuseki#> .\n@prefix tdb2: <http://jena.apache.org/2016/tdb#> .\n<#service> a fuseki:Service; fuseki:name "fish_l1";\n fuseki:endpoint [ fuseki:operation fuseki:query; fuseki:name "query" ];\n fuseki:endpoint [ fuseki:operation fuseki:update; fuseki:name "update" ];\n fuseki:endpoint [ fuseki:operation fuseki:gsp-rw; fuseki:name "data" ];\n fuseki:dataset <#dataset> .\n<#dataset> a tdb2:DatasetTDB2; tdb2:location "databases/fish_l1" .\n')
        (data / "postgres").mkdir()
        _write_private(pwfile, passwords["admin"] + "\n")
        suffix = ".exe" if os.name == "nt" else ""
        _run([pg / ("initdb" + suffix), "-D", data / "postgres" / "data", "--username=" + ROLES["admin"], "--pwfile=" + str(pwfile), "--encoding=UTF8", "--locale=C", "--auth-host=scram-sha-256", "--auth-local=scram-sha-256"], "INITDB_FAILED", timeout=120)
        pwfile.unlink()
        config = Config(root=root, data_dir=data, review_dir=root / "docs/fish/ontology-review", mapping_file=root / "config/local-server-mapping.json",
            host="127.0.0.1", port=http_port, sql={role + "_dsn": dsn for role, dsn in connections.items()},
            fuseki_url=endpoint, limits={}, backup={}, runtime=runtime, config_path=config_path)
        # Provisioning starts only PostgreSQL. Fuseki first opens its TDB2 store
        # when the operator subsequently restores or explicitly initializes.
        native = NativeServices(replace(config, runtime={**runtime, "managed_fuseki": False}))
        stage = "create-empty-databases"
        atomic_json(data / "provision-state.json", {"status": "provisioning", "stage": stage, "deployment_id": deployment_id})
        native.start()
        _empty_databases(config, passwords)
        native.stop()
        NativeServices(config).validate()
        state = {"status": "provisioned-stopped", "deployment_id": deployment_id, "databases": list(DATABASES), "application_schema": "not-created", "next": "restore-before-init-or-init-for-empty-service"}
        atomic_json(data / "provision-state.json", state)
        return {"status": state["status"], "config_path": str(config_path), "ports": {"postgres": pg_port, "fuseki": fuseki_port, "http": http_port}}
    except Exception as error:
        cleanup = "not-running"
        if native is not None:
            try:
                native.stop()
                cleanup = "stopped"
            except Exception:
                cleanup = "manual-inspection-required"
        code = error.code if isinstance(error, (ProvisionError, LifecycleError)) else "PROVISION_FAILED"
        atomic_json(data / "provision-state.json", {"status": "failed", "stage": stage, "code": code, "deployment_id": deployment_id, "cleanup": cleanup})
        raise ProvisionError(code) from None
    finally:
        pwfile.unlink(missing_ok=True)
        claim.unlink(missing_ok=True)


def main(argv=None):
    """Dependency-light command entry, with no secret-bearing diagnostics."""
    import argparse
    parser = argparse.ArgumentParser(description="Provision a fresh private local PostgreSQL17/Java21/Fuseki6.2 deployment")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--fuseki-home", type=Path, required=True)
    parser.add_argument("--pg-port", type=int, default=25459)
    parser.add_argument("--fuseki-port", type=int, default=23059)
    parser.add_argument("--http-port", type=int, default=8792)
    parser.add_argument("--allow-external-data-dir", action="store_true", help="explicitly authorize a fresh separate DATA path")
    args = parser.parse_args(argv)
    try:
        result = provision_fresh(args.root, args.data_dir or args.root / ".runtime" / "local-server", args.pg_bin, args.java_home, args.fuseki_home,
            pg_port=args.pg_port, fuseki_port=args.fuseki_port, http_port=args.http_port, allow_external_data_dir=args.allow_external_data_dir)
        print(json.dumps(result), flush=True)
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "code": error.code if isinstance(error, ProvisionError) else "PROVISION_FAILED"}), flush=True)
        return 1
