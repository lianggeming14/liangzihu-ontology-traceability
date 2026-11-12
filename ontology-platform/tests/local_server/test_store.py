"""Real PostgreSQL control-plane tests, exclusively on an explicit test DB."""
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import psycopg
from psycopg import sql
import pytest
from psycopg.conninfo import conninfo_to_dict

from local_server.store import LeaseLost, Store, StoreUnavailable
from local_server.config import contained_path


def test_connection_failures_do_not_expose_libpq_credentials():
    secret = "-".join(("synthetic", "private", "secret"))
    config = SimpleNamespace(sql={"api_dsn": f"postgresql://synthetic:{secret}@127.0.0.1:1/synthetic"})
    with pytest.raises(Exception) as failure:
        Store(config).connect()
    assert isinstance(failure.value, RuntimeError)
    assert str(failure.value) == "SQL connection unavailable"
    assert secret not in str(failure.getrepr(style="long"))


@pytest.fixture
def stores(tmp_path):
    names = {role: os.environ.get("LZO_LOCAL_TEST_" + role.upper() + "_DATABASE_URL") for role in ("admin", "api", "worker")}
    if not all(names.values()):
        pytest.skip("explicit isolated PostgreSQL fixture DSNs were not supplied")
    assert conninfo_to_dict(names["admin"])["dbname"] == "lzo_local_test", "refusing non-fixture database"
    assert conninfo_to_dict(names["admin"])["port"] == "25459", "refusing source/non-fixture port"
    data = tmp_path / "data"
    data.mkdir()
    config = SimpleNamespace(sql={role + "_dsn": dsn for role, dsn in names.items()}, data_dir=data, schema_version="1", limits={"lease_seconds": 120})
    admin = Store(config, "admin")
    with admin.connect() as conn:
        conn.execute("DROP SCHEMA IF EXISTS lzo_local CASCADE")
    admin.ensure_schema()
    yield {role: Store(config, role) for role in names}
    with admin.connect() as conn:
        conn.execute("DROP SCHEMA IF EXISTS lzo_local CASCADE")


def submit(stores, filename="batch.csv", mapping="b" * 64):
    path = stores["api"].config.data_dir / filename
    path.write_bytes(b"id,name\n1,synthetic\n")
    return stores["api"].submit_job(path, hashlib.sha256(path.read_bytes()).hexdigest(), mapping)


def test_duplicate_submission_is_persistent_but_mapping_changes_create_jobs(stores):
    first = submit(stores)
    assert submit(stores)["job_id"] == first["job_id"]
    assert submit(stores, mapping="c" * 64)["job_id"] != first["job_id"]
    assert stores["api"].get_job(first["job_id"])["status"] == "queued"
    assert len(stores["api"].list_jobs()) == 2
    schema_changed = stores["api"].submit_job(first["source_path"], first["source_sha256"], first["mapping_sha256"], schema_version="2")
    assert schema_changed["id"] != first["id"]


def test_concurrent_duplicate_submissions_converge_on_one_persistent_job(stores):
    first = submit(stores)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: stores["api"].submit_job(first["source_path"], first["source_sha256"], first["mapping_sha256"]), range(8)))
    assert {row["id"] for row in rows} == {first["id"]}
    assert len(stores["api"].list_jobs()) == 1


def test_concurrent_claims_have_one_owner_and_expired_owner_cannot_publish(stores):
    job = submit(stores)
    gate = threading.Barrier(2)
    def claim(worker):
        gate.wait()
        return stores["worker"].claim_job(worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, ("worker-a", "worker-b")))
    owners = [value for value in claimed if value]
    assert len(owners) == 1
    old = owners[0]
    old_release = stores["worker"].register_release({"sql_schema": "ls_batch_synthetic", "rdf_graph": "urn:synthetic:old"}, job_id=job["id"], worker_id=old["worker_id"], lease_token=old["lease_token"])
    with stores["admin"].connect() as conn:
        conn.execute("UPDATE lzo_local.jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job["id"],))
    new = stores["worker"].claim_job("worker-new")
    assert new["lease_token"] > old["lease_token"]
    assert not stores["worker"].check_lease(job["id"], old["worker_id"], old["lease_token"])
    for operation in (
        lambda: stores["worker"].publish_release(old_release["id"], job_id=job["id"], worker_id=old["worker_id"], lease_token=old["lease_token"]),
        lambda: stores["worker"].heartbeat(job["id"], old["worker_id"], old["lease_token"]),
        lambda: stores["worker"].finish_job(job["id"], old["worker_id"], old["lease_token"]),
        lambda: stores["worker"].fail_job(job["id"], old["worker_id"], old["lease_token"], {"code": "STALE"}),
        lambda: stores["worker"].register_release({"sql_schema": "stale"}, job_id=job["id"], worker_id=old["worker_id"], lease_token=old["lease_token"]),
    ):
        with pytest.raises(LeaseLost):
            operation()
    assert stores["api"].active_release() is None


def test_parallel_workers_cannot_import_different_jobs_at_the_same_time(stores):
    submit(stores)
    submit(stores, "second.csv", mapping="f" * 64)
    gate = threading.Barrier(2)
    def claim(worker):
        gate.wait()
        return stores["worker"].claim_job(worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, ("worker-a", "worker-b")))
    assert len([row for row in claimed if row]) == 1
    assert [row["status"] for row in stores["api"].list_jobs()].count("queued") == 1


def test_publish_switches_one_snapshot_and_failed_attempt_keeps_it(stores):
    job = submit(stores)
    claimed = stores["worker"].claim_job("worker-a")
    key = (job["id"], "worker-a", claimed["lease_token"])
    updated = stores["worker"].heartbeat(*key, stage="sql", progress={"rows": 1})
    assert updated["stage"] == "sql"
    release = stores["worker"].register_release({"sql_schema": "ls_batch_synthetic", "rdf_graph": "urn:synthetic:one", "navigation": {"manifest": "synthetic.json"}}, job_id=key[0], worker_id=key[1], lease_token=key[2])
    stores["worker"].publish_release(release["id"], job_id=key[0], worker_id=key[1], lease_token=key[2])
    stores["worker"].finish_job(*key, result={"release_id": release["id"]})
    active = stores["api"].active_release()
    assert active["id"] == release["id"]
    assert active["sql_schema"] == "ls_batch_synthetic"
    assert stores["api"].get_job(job["id"])["status"] == "succeeded"
    failed_job = submit(stores, "second.csv", mapping="d" * 64)
    failed = stores["worker"].claim_job("worker-a")
    stores["worker"].fail_job(failed_job["id"], "worker-a", failed["lease_token"], {"code": "RDF_FAILED", "message": "synthetic failure"}, retryable=True)
    assert stores["api"].active_release()["id"] == release["id"]
    assert stores["api"].get_job(failed_job["id"])["error"]["retryable"] is True
    stores["worker"].retry_job(failed_job["id"])
    assert stores["worker"].claim_job("worker-retry")["attempts"] == 2


def test_api_can_register_jobs_but_cannot_create_schema_or_activate_release(stores):
    assert submit(stores)["status"] == "queued"
    with pytest.raises(PermissionError):
        stores["api"].ensure_schema()
    with pytest.raises(PermissionError):
        stores["api"].register_release({"sql_schema": "private"})
    with stores["api"].connect() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE SCHEMA forbidden_api_schema")
    with stores["api"].connect() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE lzo_local.state SET active_release_id=NULL")


def test_source_path_must_stay_inside_private_data(stores, tmp_path):
    outside = tmp_path / "outside.csv"
    outside.write_text("id\n1", encoding="utf-8")
    with pytest.raises(ValueError):
        stores["api"].submit_job(outside, "a" * 64, "b" * 64)


def test_bootstrap_release_registration_is_immutable_and_idempotent(stores):
    metadata = {"release_id": "00000000-0000-4000-8000-000000000001", "sql_schema": "synthetic", "rdf_graph": "urn:synthetic:bootstrap"}
    first = stores["admin"].register_release(metadata)
    assert stores["admin"].register_release(metadata)["id"] == first["id"]
    with pytest.raises(ValueError):
        stores["admin"].register_release({**metadata, "rdf_graph": "urn:changed"})
    stores["admin"].publish_release(first["id"])
    assert stores["api"].active_release()["rdf_graph"] == "urn:synthetic:bootstrap"


def test_lease_expiring_during_publication_cannot_switch_active_pointer(stores):
    job = submit(stores)
    claimed = stores["worker"].claim_job("worker-a")
    lease = {"job_id": job["id"], "worker_id": "worker-a", "lease_token": claimed["lease_token"]}
    release = stores["worker"].register_release({"sql_schema": "synthetic", "rdf_graph": "urn:synthetic:boundary"}, **lease)
    # A real trigger moves expiry across the final publication boundary without
    # timing-dependent sleeps. Its side effect rolls back with a rejected publish.
    with stores["admin"].connect() as conn:
        conn.execute("""CREATE FUNCTION lzo_local.fixture_expire_lease() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                UPDATE lzo_local.jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=NEW.job_id;
                RETURN NEW;
            END $$""")
        conn.execute("CREATE TRIGGER fixture_expire_lease BEFORE UPDATE ON lzo_local.releases FOR EACH ROW EXECUTE FUNCTION lzo_local.fixture_expire_lease()")
    with pytest.raises(LeaseLost):
        stores["worker"].publish_release(release["id"], **lease)
    assert stores["api"].active_release() is None
    assert stores["api"].get_release(release["id"])["status"] == "ready"


def test_persisted_file_references_survive_a_new_data_root(stores, tmp_path):
    job = submit(stores)
    data = stores["admin"].config.data_dir
    public = data / "public"
    public.mkdir()
    (public / "manifest.json").write_text('{"synthetic":true}', encoding="utf-8")
    release = stores["admin"].register_release({"navigation_dir": str(public), "manifest_path": str(public / "manifest.json"), "source_path": str(data / "batch.csv"), "navigation": {"data_dir": str(public), "manifest_path": str(public / "manifest.json")}, "provenance": {"business_source": "C:/source-business-record"}})
    assert job["source_path"] == "batch.csv"
    assert release["navigation_dir"] == "public"
    assert release["manifest_path"] == "public/manifest.json"
    assert release["path_base"] == "data"
    relocated = tmp_path / "new-machine-data"
    data.rename(relocated)
    config = SimpleNamespace(**{**vars(stores["api"].config), "data_dir": relocated})
    new_store = Store(config)
    persisted_job = new_store.get_job(job["id"])
    persisted_release = new_store.get_release(release["id"])
    assert contained_path(config.data_dir, persisted_job["source_path"]).read_bytes() == b"id,name\n1,synthetic\n"
    assert contained_path(config.data_dir, persisted_release["manifest_path"]).read_text(encoding="utf-8") == '{"synthetic":true}'
    assert persisted_release["provenance"]["business_source"] == "C:/source-business-record"


def test_legacy_navigation_references_use_configured_review_root(stores, tmp_path):
    review = tmp_path / "legacy-review"
    review.mkdir()
    stores["admin"].config.review_dir = review
    release = stores["admin"].register_release({"legacy_snapshot": True, "navigation_dir": str(review), "manifest_path": str(review / "data/manifest.json")})
    assert release["path_base"] == "review"
    assert release["navigation_dir"] == "."
    assert release["manifest_path"] == "data/manifest.json"


def test_legacy_snapshot_can_reference_copied_self_contained_assets(stores):
    data = stores["admin"].config.data_dir
    release = stores["admin"].register_release({"legacy_snapshot": True, "path_base": "data", "navigation_dir": str(data / "releases/legacy"), "manifest_path": str(data / "releases/legacy/data/manifest.json")})
    assert release["path_base"] == "data"
    assert release["navigation_dir"] == "releases/legacy"


def test_explicit_initialization_restores_service_connect_after_restored_database_acl(stores):
    admin = stores["admin"]
    database = conninfo_to_dict(admin.dsn())["dbname"]
    roles = [conninfo_to_dict(admin.dsn(role))["user"] for role in ("api", "worker")]
    with admin.connect() as conn:
        conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
        for role in roles:
            conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(database), sql.Identifier(role)))
    try:
        for role in ("api", "worker"):
            with pytest.raises(StoreUnavailable):
                stores[role].connect()
        admin.ensure_schema()
        job = submit(stores)
        assert stores["api"].get_job(job["id"])["status"] == "queued"
        claimed = stores["worker"].claim_job("restored-worker")
        assert claimed["id"] == job["id"]
        finished = stores["worker"].finish_job(job["id"], "restored-worker", claimed["lease_token"], {"synthetic": True})
        assert finished["status"] == "succeeded"
        with stores["api"].connect() as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("CREATE SCHEMA forbidden_after_restore")
    finally:
        # Fixture cleanup also runs after RED so subsequent tests are not locked
        # out. It grants only the two dedicated fixture roles, never PUBLIC.
        with admin.connect() as conn:
            for role in roles:
                conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(role)))


def test_api_lists_all_release_snapshots_in_stable_creation_order(stores):
    identifiers = ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002", "00000000-0000-4000-8000-000000000003"]
    for number, identifier in enumerate(identifiers, 1):
        stores["admin"].register_release({"release_id": identifier, "rdf_graph": "urn:synthetic:" + str(number)})
    with stores["admin"].connect() as conn:
        conn.execute("UPDATE lzo_local.releases SET created_at='2026-01-01T00:00:00Z'")
    listed = stores["api"].list_releases(limit=2)
    assert [row["release_id"] for row in listed] == [identifiers[2], identifiers[1]]
    assert listed[0]["rdf_graph"] == "urn:synthetic:3"
    assert [row["release_id"] for row in stores["api"].list_releases(limit=2, offset=2)] == [identifiers[0]]
    assert stores["api"].list_releases(offset=3) == []


@pytest.mark.parametrize("limit,offset", [(0, 0), (1001, 0), (True, 0), (1.5, 0), (1, -1), (1, True), (1, "0")])
def test_release_listing_rejects_invalid_paging_before_connecting(limit, offset):
    with pytest.raises(ValueError):
        Store(SimpleNamespace(sql={}), "api").list_releases(limit=limit, offset=offset)
