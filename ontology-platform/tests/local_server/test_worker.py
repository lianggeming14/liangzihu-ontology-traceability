"""External service faults and expired leases must preserve the active release."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from decimal import Decimal
from datetime import timezone
import sys
from types import SimpleNamespace
from uuid import uuid4
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class Control:
    def __init__(self):
        self.active = {"release_id": "previous"}
        self.events = []
        self.alive = True

    def heartbeat(self, *args, stage=None, **kwargs):
        if not self.alive:
            raise RuntimeError("lease expired")
        self.events.append(stage)

    def check_lease(self, *args):
        return self.alive

    def register_release(self, metadata, **kwargs):
        assert self.alive
        self.pending = {**metadata, "release_id": "new-release"}
        return self.pending

    def publish_release(self, release_id, **kwargs):
        assert self.alive
        self.active = self.pending
        return self.active

    def finish_job(self, *args, **kwargs):
        self.finished = True

    def fail_job(self, *args, **kwargs):
        self.failed = True


def setup_job(tmp_path):
    from local_server.importer import load_mapping, input_mapping_hash
    mapping = load_mapping(ROOT / "config/local-server-mapping.json")
    data = tmp_path / "data"
    data.mkdir()
    source = data / "ponds.csv"
    source.write_text("id,farm_id,area\np1,unknown,10.123456789\n", encoding="utf-8")
    config = SimpleNamespace(data_dir=data, mapping_file=ROOT / "config/local-server-mapping.json",
        limits={"min_free_disk_bytes": 1}, schema_version="1")
    job = {"job_id": "86e40971-cc8b-43a8-9e3f-6b1ae62a9491", "lease_token": 1,
           "source_path": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
           "mapping_sha256": input_mapping_hash(mapping, source.name), "schema_version": "1"}
    return config, job


def test_success_activates_only_after_sql_rdf_shacl_and_file_verification(tmp_path, monkeypatch):
    from local_server import worker
    from local_server.rdf import verify_readback
    config, job = setup_job(tmp_path)
    state = Control()
    monkeypatch.setattr(worker, "store_batch", lambda *args, **kwargs: {"status": "passed", "schema": "new"})
    monkeypatch.setattr(worker, "load_and_verify", lambda config, generated, **kwargs: verify_readback(generated, generated["nt_path"]))
    result = worker.process_job(config, state, job, "worker-1")
    assert state.active["release_id"] == "new-release"
    assert state.active["verification"]["sql"]["status"] == "passed"
    assert state.active["verification"]["rdf"]["full_terms_equal"] is True
    assert state.active["verification"]["shacl"]["status"] == "passed"
    assert state.finished
    assert result["release_id"] == "new-release"


@pytest.mark.parametrize("stage", ["sql", "rdf", "lease"])
def test_failed_stage_preserves_old_release(tmp_path, monkeypatch, stage):
    from local_server import worker
    config, job = setup_job(tmp_path)
    state = Control()

    def sql(*args, **kwargs):
        if stage == "sql":
            raise ValueError("database readback failed")
        return {"status": "passed"}

    def rdf(*args, **kwargs):
        if stage == "lease":
            from local_server.rdf import verify_readback
            generated = args[1]
            proof = verify_readback(generated, generated["nt_path"])
            state.alive = False
            return proof
        raise ValueError("RDF readback failed")

    monkeypatch.setattr(worker, "store_batch", sql)
    monkeypatch.setattr(worker, "load_and_verify", rdf)
    with pytest.raises((ValueError, RuntimeError)):
        worker.process_job(config, state, job, "worker-1")
    assert state.active == {"release_id": "previous"}
    assert not hasattr(state, "finished")


def test_changed_source_or_mapping_is_rejected_before_database(tmp_path, monkeypatch):
    from local_server import worker
    config, job = setup_job(tmp_path)
    Path(job["source_path"]).write_text("id\nchanged\n", encoding="utf-8")
    monkeypatch.setattr(worker, "store_batch", lambda *args, **kwargs: pytest.fail("SQL must not be reached"))
    with pytest.raises(ValueError, match="hash"):
        worker.process_job(config, Control(), job, "worker-1")


def test_source_changed_during_private_copy_cannot_be_published(tmp_path, monkeypatch):
    from local_server import worker
    config, job = setup_job(tmp_path)
    build_batch = worker.build_batch

    def changed(*args, **kwargs):
        Path(job["source_path"]).write_text("id,area\nchanged,12\n", encoding="utf-8")
        return build_batch(*args, **kwargs)

    monkeypatch.setattr(worker, "build_batch", changed)
    monkeypatch.setattr(worker, "store_batch", lambda *args, **kwargs: pytest.fail("Changed source must not reach SQL"))
    state = Control()
    with pytest.raises(ValueError, match="hash"):
        worker.process_job(config, state, job, "worker-1")
    assert state.active == {"release_id": "previous"}


def test_relative_job_paths_and_release_artifacts_survive_data_directory_move(tmp_path, monkeypatch):
    from local_server import worker
    from local_server.config import contained_path
    from local_server.rdf import verify_readback
    config, job = setup_job(tmp_path)
    job["source_path"] = "ponds.csv"
    moved = tmp_path / "moved-data"
    shutil.copytree(config.data_dir, moved)
    config.data_dir = moved
    monkeypatch.setattr(worker, "store_batch", lambda *args, **kwargs: {"status": "passed", "schema": "new"})
    monkeypatch.setattr(worker, "load_and_verify", lambda config, generated, **kwargs: verify_readback(generated, generated["nt_path"]))
    release = worker.process_job(config, Control(), job, "worker-relative")
    assert release["path_base"] == "data"
    for key in ("navigation_dir", "manifest_path", "source_path"):
        assert not Path(release[key]).is_absolute()
    assert str(tmp_path) not in str(release)
    moved_again = tmp_path / "restored-data"
    shutil.copytree(moved, moved_again)
    assert contained_path(moved_again, release["manifest_path"]).is_file()
    assert contained_path(moved_again, release["source_path"]).read_bytes() == (moved_again / "ponds.csv").read_bytes()


@pytest.mark.skipif(os.environ.get("LZO_IMPORT_FIXTURE") != "1", reason="explicit isolated native import fixture not requested")
def test_real_new_postgres_fuseki_fixture_success_duplicate_failure_and_retry(monkeypatch):
    """Native evidence uses only 25459/lzo_import_fixture_db and /import_fixture."""
    import httpx
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from dotenv import dotenv_values
    from local_server.config import Config
    from local_server.importer import build_batch, file_hash, input_mapping_hash, load_mapping
    from local_server.store import Store
    from local_server import worker
    from local_server.rdf import save_json, verify_files
    from fish_rdf_sample import uri_factory

    private = dotenv_values(ROOT / ".runtime/local-server/private.env")
    admin_dsn = private["LZO_LOCAL_ADMIN_DATABASE_URL"]
    target = conninfo_to_dict(admin_dsn)
    assert target["port"] == "25459", "refusing original/non-fixture PostgreSQL"

    def connect(dsn, **kwargs):
        try:
            return psycopg.connect(dsn, connect_timeout=5, **kwargs)
        except psycopg.Error:
            raise RuntimeError("Isolated native PostgreSQL fixture unavailable") from None

    database = "lzo_import_fixture_db"
    with connect(make_conninfo(admin_dsn, dbname="postgres"), autocommit=True) as connection:
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    endpoint = "http://127.0.0.1:23059/import_fixture"
    with httpx.Client(trust_env=False, timeout=30) as client:
        response = client.get("http://127.0.0.1:23059/$/datasets")
        response.raise_for_status()
        existing = {entry.get("ds.name", "").lstrip("/") for entry in response.json()["datasets"]}
        if "import_fixture" not in existing:
            response = client.post("http://127.0.0.1:23059/$/datasets", data={"dbName": "import_fixture", "dbType": "tdb2"})
            response.raise_for_status()
    build_dir = ROOT / ".runtime/local-server-build/import-fixture"
    build_dir.mkdir(parents=True, exist_ok=True)
    main = json.loads((ROOT / ".runtime/local-server/config.json").read_text(encoding="utf-8-sig"))
    main.update(root=str(ROOT), data_dir=str(build_dir / "data"), review_dir=str(ROOT / "docs"),
                fuseki_url=endpoint, fuseki_allowed_targets=[endpoint], backup={}, runtime={},
                mapping_file=str(build_dir / "mapping.json"))
    main.pop("env_file", None)
    for role in ("admin", "api", "worker"):
        name = "LZO_IMPORT_FIXTURE_" + role.upper() + "_DSN"
        monkeypatch.setenv(name, make_conninfo(private["LZO_LOCAL_" + role.upper() + "_DATABASE_URL"], dbname=database))
        main["sql"][role + "_dsn_env"] = name
        main["sql"].pop(role + "_dsn", None)
    main["sql"]["allowed_targets"] = [{"host": "127.0.0.1", "port": 25459, "database": database}]
    main["limits"].update(min_free_disk_bytes=1024 * 1024, lease_seconds=120)
    mapping_document = json.loads((ROOT / "config/local-server-mapping.json").read_text(encoding="utf-8"))
    mapping_document["version"] = "synthetic-native-import-fixture/1"
    mapping_document["definitions"]["tables"]["ponds"]["columns"]["depth_m"] = {"type": "number", "unit": "m"}
    mapping_document["definitions"]["tables"]["ponds"]["columns"]["observed_at"] = {"type": "string", "format": "date-time"}
    mapping_document["definitions"]["tables"]["ponds"]["columns"]["count"] = {"type": "integer"}
    save_json(build_dir / "mapping.json", mapping_document)
    save_json(build_dir / "config.json", main)
    config = Config.load(build_dir / "config.json")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    admin, api, control = Store(config, "admin"), Store(config, "api"), Store(config, "worker")
    admin.ensure_schema()
    mapping = load_mapping(config.mapping_file)
    run_id = uuid4().hex[:12]

    def enqueue(suffix, depth, *, timestamp=None, count=None):
        source = config.data_dir / "uploads" / (run_id + suffix) / "batch.zip"
        source.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("farms.csv", "id,name,is_synthetic\nf" + run_id + ",Synthetic Farm,true\n")
            extra_header = (",observed_at" if timestamp is not None else "") + (",count" if count is not None else "")
            extra_value = ("," + timestamp if timestamp is not None else "") + ("," + count if count is not None else "")
            archive.writestr("ponds.csv", "id,name,farm_id,depth_m,is_synthetic" + extra_header + "\np" + run_id + suffix + ",Synthetic Pond,f" + run_id + "," + depth + ",true" + extra_value + "\nu" + run_id + suffix + ",Unresolved Pond,missing,2.0,true" + extra_value + "\n")
        job = api.submit_job(source, file_hash(source), input_mapping_hash(mapping, source.name), metadata={"data_nature": "synthetic_fixture"})
        return source, job

    def execute(job, worker_id):
        claimed = control.claim_job(worker_id)
        assert claimed and claimed["job_id"] == job["job_id"]
        return worker.process_job(config, control, claimed, worker_id)

    source, first_job = enqueue("a", "1.234567890123456789", timestamp="2026-11-12T12:00:00.123456+08:00")
    first = execute(first_job, "native-fixture-a")
    assert api.get_job(first_job["job_id"])["status"] == "succeeded"
    assert api.submit_job(source, file_hash(source), input_mapping_hash(mapping, source.name))["job_id"] == first_job["job_id"]
    assert first["path_base"] == "data" and not Path(first["manifest_path"]).is_absolute()
    schema = first["sql_schema"]
    with api.connect() as connection:
        typed = connection.execute(sql.SQL("SELECT depth_m,observed_at FROM {}.data_ponds WHERE id=%s").format(sql.Identifier(schema)), ("p" + run_id + "a",)).fetchone()
        assert typed["depth_m"] == Decimal("1.234567890123456789")
        assert typed["observed_at"].astimezone(timezone.utc).isoformat() == "2026-11-12T04:00:00.123456+00:00"
    with api.connect() as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(sql.SQL("SELECT payload FROM {}.raw_records").format(sql.Identifier(schema)))
    assert first["counts"]["instances"] == 3
    assert first["counts"]["resolved_relations"] == 1
    u = uri_factory(first["namespace"])
    snapshot = build_batch(source, build_dir / "source-check" / run_id, mapping)["snapshot"]
    pond = next(node for node in snapshot["nodes"] if node["source_pk"] == "p" + run_id + "a")
    predicate = u("relation", "ponds", "farm_id", "farms")
    query = "SELECT ?depth WHERE { GRAPH <" + first["rdf_graph"] + "> { <" + str(u("instance", pond["node_id"])) + "> <" + str(u("property", "ponds", "depth_m")) + "> ?depth ; <" + str(predicate) + "> ?farm . ?farm <" + str(predicate) + ":inverse> <" + str(u("instance", pond["node_id"])) + "> } }"
    with httpx.Client(trust_env=False, timeout=30) as client:
        response = client.post(endpoint + "/query", data={"query": query})
        response.raise_for_status()
        values = response.json()["results"]["bindings"]
    assert values[0]["depth"]["value"] == "1.234567890123456789"
    assert values[0]["depth"]["datatype"] == "http://www.w3.org/2001/XMLSchema#decimal"
    first_files = dict(first["navigation"]["files"])
    _, second_job = enqueue("b", "8.765432109876543219", timestamp="2026-11-12T12:00:00.123456000Z")
    real_rdf = worker.load_and_verify

    def fail_rdf(*args, **kwargs):
        raise RuntimeError("Synthetic fixture: RDF transport unavailable after SQL commit")

    monkeypatch.setattr(worker, "load_and_verify", fail_rdf)
    with pytest.raises(RuntimeError, match="Synthetic fixture"):
        execute(second_job, "native-fixture-fail")
    failed = api.get_job(second_job["job_id"])
    assert failed["status"] == "failed"
    assert api.active_release()["release_id"] == first["release_id"]
    control.retry_job(second_job["job_id"])
    monkeypatch.setattr(worker, "load_and_verify", real_rdf)
    second = execute(second_job, "native-fixture-retry")
    assert second["verification"]["sql"]["schema_created"] is False
    assert api.get_job(second_job["job_id"])["attempts"] == 2
    assert second["release_id"] != first["release_id"]
    assert second["rdf_graph"] != first["rdf_graph"]
    verify_files(config.data_dir / first["navigation_dir"], first_files)
    assert api.get_release(first["release_id"])["rdf_graph"] == first["rdf_graph"]

    def schema_inventory():
        with api.connect() as connection:
            return {row["nspname"] for row in connection.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ls_batch_%'").fetchall()}

    def graph_inventory():
        with httpx.Client(trust_env=False, timeout=30) as client:
            response = client.post(endpoint + "/query", data={"query": "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"})
            response.raise_for_status()
            return {row["g"]["value"] for row in response.json()["results"]["bindings"]}

    schemas_before_invalid, graphs_before_invalid = schema_inventory(), graph_inventory()
    invalid_cases = [
        {"timestamp": "2026-11-12 12:00:00.123456789+00:00"},
        {"timestamp": "2026-11-12t12:00:00.123456789+00:00"},
        {"timestamp": "2026-11-12T12:00:00.123456789Z"},
        {"count": "1e200000"},
    ]
    for index, invalid in enumerate(invalid_cases):
        _, invalid_job = enqueue("invalid" + str(index), "1.0", **invalid)
        with pytest.raises(ValueError, match="date-time|numeric"):
            execute(invalid_job, "native-fixture-invalid-" + str(index))
        assert api.get_job(invalid_job["job_id"])["status"] == "failed"
        assert api.active_release()["release_id"] == second["release_id"]
    assert schema_inventory() == schemas_before_invalid
    assert graph_inventory() == graphs_before_invalid
    report = {"status": "passed", "data_nature": "synthetic_fixture", "postgres_port": 25459,
              "database": database, "fuseki_dataset": "import_fixture", "instances": first["counts"]["instances"],
              "resolved_relations": 1, "unresolved_relations": 1,
              "exact_decimal": "1.234567890123456789", "sql_full_readback": True,
              "exact_timestamptz_utc": "2026-11-12T04:00:00.123456+00:00",
              "jena_full_terms_equal": second["verification"]["rdf"]["full_terms_equal"],
              "bidirectional_relation_sparql": "passed", "duplicate_reuses_job": True,
              "sql_success_rdf_failure_preserves_release": True, "retry_reuses_verified_sql": True,
              "old_navigation_hashes_unchanged": True, "raw_api_privilege_denied": True,
              "preflight_rejected_without_new_sql_or_rdf": len(invalid_cases),
              "first_release_id": first["release_id"], "second_release_id": second["release_id"]}
    save_json(build_dir / "native-report.json", report)
