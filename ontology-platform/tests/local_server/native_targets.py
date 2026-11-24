"""Fail-closed targets for destructive, synthetic-only native regressions.

No default private.env is read. Credentials come exclusively from explicit test
environment variables; the JSON manifest contains only public target identity.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class NativeTargetError(ValueError):
    """Sanitized guard failure; never include the DSN or parser exception."""


PROTECTED_PORTS = {25449, 25459, 23049, 23059}
ROLES = ("admin", "api", "worker")
ENV_PREFIX = "LZO_LOCAL_TEST_"


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise NativeTargetError("native test manifest fields are invalid")


def _port(value):
    if type(value) is not int or not 1024 <= value <= 65535:
        raise NativeTargetError("native test port is invalid")
    if value in PROTECTED_PORTS:
        raise NativeTargetError("protected native service port is forbidden")
    return value


def _path(value):
    try:
        path = Path(value)
        if not isinstance(value, str) or not path.is_absolute() or not path.is_dir():
            raise ValueError()
        return path.resolve(strict=True)
    except (TypeError, OSError, ValueError):
        raise NativeTargetError("native test paths must be existing absolute directories") from None


def _dsn_fields(dsn, port):
    try:
        values = conninfo_to_dict(dsn)
        if set(values) - {"host", "port", "dbname", "user", "password", "sslmode", "connect_timeout", "application_name"}:
            raise ValueError()
        if values.get("host") not in ("127.0.0.1", "::1"):
            raise ValueError()
        actual_port = int(values.get("port", "0"))
        if actual_port in PROTECTED_PORTS:
            raise NativeTargetError("protected native service port is forbidden")
        if str(actual_port) != values.get("port") or actual_port != port:
            raise ValueError()
        if not re.fullmatch(r"test_[a-z0-9_]{1,58}", values.get("dbname", "")) or not values.get("user"):
            raise ValueError()
        return values
    except NativeTargetError:
        raise
    except Exception:
        raise NativeTargetError("explicit native test DSN target is invalid") from None


def _inspect_fuseki_process(pid):
    import psutil
    from local_server.lifecycle import process_identity
    process = psutil.Process(pid)
    ports = [item.laddr.port for item in process.net_connections(kind='tcp')
             if item.status == psutil.CONN_LISTEN and item.laddr.ip in ('127.0.0.1', '::1')]
    return {**process_identity(pid), 'listening_ports': ports}


@dataclass(frozen=True)
class NativeTargets:
    fixture_id: str
    source_port: int
    source_data_dir: Path
    restore_port: int
    restore_data_dir: Path
    fuseki_port: int
    fuseki_state_dir: Path
    fuseki_dataset: str
    pg_bin: Path
    dsns: dict = field(repr=False)
    restore_admin: str = field(repr=False)

    @classmethod
    def from_environment(cls, environ=None):
        environ = os.environ if environ is None else environ
        if any(environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")):
            raise NativeTargetError("indirect libpq environment is forbidden for native tests")
        try:
            manifest_path = Path(environ["LZO_NATIVE_TEST_MANIFEST"])
            if not manifest_path.is_absolute():
                raise ValueError()
            payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (KeyError, TypeError, ValueError, OSError):
            raise NativeTargetError("explicit LZO_NATIVE_TEST_MANIFEST is required") from None
        _keys(payload, ("contract", "synthetic_only", "fixture_id", "postgres", "fuseki", "pg_bin"))
        if payload["contract"] != "lzo-native-test-targets/1" or payload["synthetic_only"] is not True:
            raise NativeTargetError("native test manifest must declare synthetic-only contract")
        fixture_id = payload["fixture_id"]
        if not isinstance(fixture_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{7,63}", fixture_id):
            raise NativeTargetError("native test fixture identity is invalid")
        _keys(payload["postgres"], ("source", "restore"))
        for value in payload["postgres"].values():
            _keys(value, ("port", "data_dir"))
        _keys(payload["fuseki"], ("port", "state_dir", "dataset"))
        source, restore, fuseki = payload["postgres"]["source"], payload["postgres"]["restore"], payload["fuseki"]
        ports = [_port(value["port"]) for value in (source, restore, fuseki)]
        if len(set(ports)) != len(ports):
            raise NativeTargetError("native source, restore and RDF ports must be separate")
        paths = [_path(source["data_dir"]), _path(restore["data_dir"]), _path(fuseki["state_dir"])]
        if any(a.is_relative_to(b) or b.is_relative_to(a) for index, a in enumerate(paths) for b in paths[index + 1:]):
            raise NativeTargetError("native source, restore and RDF data directories must be separate")
        if not isinstance(fuseki["dataset"], str) or not re.fullmatch(r"test_[a-z0-9_]{1,58}", fuseki["dataset"]):
            raise NativeTargetError("native RDF dataset must have a dedicated test prefix")
        dsns = {role: environ.get(ENV_PREFIX + role.upper() + "_DATABASE_URL", "") for role in ROLES}
        fields = [_dsn_fields(dsn, ports[0]) for dsn in dsns.values()]
        if len({(value["host"], value["port"], value["dbname"]) for value in fields}) != 1:
            raise NativeTargetError("native admin, API and worker must use the same instance and database")
        restore_dsn = environ.get(ENV_PREFIX + "RESTORE_ADMIN_DATABASE_URL", "")
        _dsn_fields(restore_dsn, ports[1])
        return cls(fixture_id, ports[0], paths[0], ports[1], paths[1], ports[2], paths[2], fuseki["dataset"], _path(payload["pg_bin"]), dsns, restore_dsn)

    @property
    def fuseki_url(self):
        return f"http://127.0.0.1:{self.fuseki_port}/{self.fuseki_dataset}"

    def admin_dsn(self, cluster="source"):
        if cluster not in ("source", "restore"):
            raise NativeTargetError("unknown native test cluster")
        return self.dsns["admin"] if cluster == "source" else self.restore_admin

    def verify_cluster(self, cluster="source", *, connect=None):
        """Read-only identity check, called before granting any DDL access."""
        connection = None
        try:
            connection = (connect or psycopg.connect)(self.admin_dsn(cluster), connect_timeout=5,
                options="-c default_transaction_read_only=on", autocommit=True)
            actual = connection.execute("SHOW data_directory").fetchone()[0]
            expected = self.source_data_dir if cluster == "source" else self.restore_data_dir
            if Path(actual).resolve() != expected:
                raise NativeTargetError("native PostgreSQL data directory does not match the manifest")
        except NativeTargetError:
            raise
        except Exception:
            raise NativeTargetError("native PostgreSQL identity probe failed") from None
        finally:
            if connection is not None:
                connection.close()

    def verify_fuseki(self, *, inspect_process=None):
        """Bind the RDF URL to the declared live runner and private TDB store."""
        try:
            from rdflib import Graph, Literal, Namespace
            state = self.fuseki_state_dir
            config = state / 'config.ttl'
            if not config.resolve().is_relative_to(state):
                raise ValueError()
            saved = json.loads((state / 'process.json').read_text(encoding='utf-8'))
            actual = (inspect_process or _inspect_fuseki_process)(saved['pid'])
            command = actual['command']
            indexes = [index for index, item in enumerate(command) if Path(item).name == 'LocalFusekiRunner.java']
            if (actual['pid'] != saved['pid'] or abs(actual['created'] - saved['created']) >= .01
                    or Path(actual['exe']).resolve() != Path(saved['exe']).resolve()
                    or Path(actual['cwd']).resolve() != state
                    or self.fuseki_port not in actual['listening_ports'] or len(indexes) != 1):
                raise ValueError()
            index = indexes[0]
            if Path(command[index + 1]).resolve() != config.resolve() or command[index + 2] != str(self.fuseki_port):
                raise ValueError()
            graph = Graph().parse(config, format='turtle')
            fuseki, tdb = Namespace('http://jena.apache.org/fuseki#'), Namespace('http://jena.apache.org/2016/tdb#')
            services = list(graph.subjects(fuseki.name, Literal(self.fuseki_dataset)))
            if len(services) != 1:
                raise ValueError()
            datasets = list(graph.objects(services[0], fuseki.dataset))
            if len(datasets) != 1:
                raise ValueError()
            locations = list(graph.objects(datasets[0], tdb.location))
            if len(locations) != 1 or not (state / str(locations[0])).resolve().is_relative_to(state):
                raise ValueError()
        except Exception:
            raise NativeTargetError('native Fuseki identity does not match the test manifest') from None

    def connect_admin(self, cluster="source", **kwargs):
        # Recheck identity before each setup/cleanup connection; no cached grant.
        self.verify_cluster(cluster)
        try:
            return psycopg.connect(self.admin_dsn(cluster), connect_timeout=5, **kwargs)
        except psycopg.Error:
            raise NativeTargetError("native PostgreSQL fixture unavailable") from None

    @contextmanager
    def database(self, purpose, *, cluster="source"):
        """Own a unique database; never DROP a supplied/preexisting database."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,19}", purpose):
            raise NativeTargetError("native test database purpose is invalid")
        name = "test_" + purpose + "_" + uuid4().hex[:16]
        created = False
        try:
            with self.connect_admin(cluster, autocommit=True) as connection:
                connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created = True
            base = self.dsns if cluster == "source" else {"admin": self.restore_admin}
            yield name, {role: make_conninfo(dsn, dbname=name) for role, dsn in base.items()}
        finally:
            if created:
                with self.connect_admin(cluster, autocommit=True) as connection:
                    connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
