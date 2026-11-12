"""Fresh provisioning never initializes an existing or external data directory."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _provision(data_dir, **kwargs):
    from local_server.provision import provision_fresh
    return provision_fresh(ROOT, data_dir, ROOT / "missing-pg", ROOT / "missing-java", ROOT / "missing-fuseki", **kwargs)


def test_provision_rejects_existing_data_before_running_tools(tmp_path):
    data = ROOT / ".runtime" / ("test-provision-" + tmp_path.name)
    data.mkdir(parents=True)
    sentinel = data / "keep.txt"
    sentinel.write_text("existing data", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="DATA_NOT_EMPTY"):
            _provision(data)
        assert sentinel.read_text(encoding="utf-8") == "existing data"
        assert sorted(path.name for path in data.iterdir()) == ["keep.txt"]
    finally:
        sentinel.unlink()
        data.rmdir()


def test_provision_rejects_external_data_before_creating_anything(tmp_path):
    # Remains outside ROOT even when pytest --basetemp is inside ROOT/.runtime.
    data = ROOT.parent / ("provision-external-" + tmp_path.name)
    with pytest.raises(ValueError, match="DATA_OUTSIDE_WORKSPACE"):
        _provision(data)
    assert not data.exists()


def test_external_data_requires_explicit_opt_in_and_still_checks_tools(tmp_path):
    data = ROOT.parent / ("provision-opt-in-" + tmp_path.name)
    with pytest.raises(ValueError, match="TOOLS_NOT_AVAILABLE"):
        _provision(data, allow_external_data_dir=True, pg_port=25469, fuseki_port=23069, http_port=8802)
    assert not data.exists()


@pytest.mark.parametrize("ports", [
    {"pg_port": 25449}, {"fuseki_port": 23049}, {"http_port": 25449},
    {"pg_port": 20000, "fuseki_port": 20000}, {"pg_port": True}, {"http_port": 65536},
])
def test_provision_rejects_source_invalid_or_duplicate_ports(tmp_path, ports):
    data = ROOT / ".runtime" / ("test-provision-" + tmp_path.name)
    with pytest.raises(ValueError, match="PORT_REJECTED"):
        _provision(data, **ports)
    assert not data.exists()


def test_provision_rejects_a_listening_port_before_creating_data(tmp_path):
    data = ROOT / ".runtime" / ("test-provision-" + tmp_path.name)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(ValueError, match="PORT_IN_USE"):
            _provision(data, pg_port=listener.getsockname()[1], fuseki_port=23169, http_port=8812)
    assert not data.exists()


def test_provision_rejects_symlinked_data_parent(tmp_path):
    parent = ROOT / ".runtime" / ("test-provision-link-" + tmp_path.name)
    try:
        parent.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit this user to create a directory symlink")
    try:
        with pytest.raises(ValueError, match="DATA_LINK_REJECTED"):
            _provision(parent / "new")
        assert not (tmp_path / "new").exists()
    finally:
        parent.unlink()


def test_provision_missing_tools_does_not_leave_a_partial_environment(tmp_path):
    data = ROOT / ".runtime" / ("test-provision-" + tmp_path.name)
    with pytest.raises(ValueError, match="TOOLS_NOT_AVAILABLE"):
        _provision(data, pg_port=25469, fuseki_port=23069, http_port=8802)
    assert not data.exists()


@pytest.mark.skipif(not os.environ.get("LOCAL_SERVER_PROVISION_NATIVE"), reason="requires explicit isolated native PostgreSQL17/Java21/Fuseki6.2 fixture")
def test_native_provision_empty_four_databases_then_explicit_init_and_graceful_lifecycle():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from dotenv import dotenv_values
    from local_server.cli import load_config
    from local_server.lifecycle import NativeServices
    from local_server.provision import provision_fresh
    from local_server.store import Store

    tools = Path(os.environ["LOCAL_SERVER_PROVISION_TOOLS"])
    data = ROOT / ".runtime" / "local-server-build" / os.environ.get("LOCAL_SERVER_PROVISION_FIXTURE", "provision-fixture")
    result = provision_fresh(ROOT, data, tools / "postgresql-17.11" / "bin", tools / "java-21", tools / "fuseki-6.2.0", pg_port=25469, fuseki_port=23069, http_port=8802)
    assert result["status"] == "provisioned-stopped"
    assert result["ports"] == {"postgres": 25469, "fuseki": 23069, "http": 8802}
    private = dotenv_values(data / "private.env")
    assert len({conninfo_to_dict(private[key])["password"] for key in ("LZO_LOCAL_ADMIN_DATABASE_URL", "LZO_LOCAL_API_DATABASE_URL", "LZO_LOCAL_WORKER_DATABASE_URL")}) == 3
    assert not any(secret in json.dumps(result) for secret in private.values())
    assert not list(data.glob("*.pwfile"))
    config = load_config(result["config_path"])
    native = NativeServices(config)
    assert native.status() == {"postgres": "stopped", "fuseki": "stopped"}
    try:
        native.start()
        for database in ("lzo", "lzo_gis", "lzo_timeseries", "lzo_catalog"):
            with psycopg.connect(private["LZO_LOCAL_" + database.upper() + "_DATABASE_URL"]) as connection:
                assert connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')").fetchone()[0] == 0
                assert connection.execute("SELECT count(*) FROM pg_namespace WHERE nspname='lzo_local'").fetchone()[0] == 0
        with psycopg.connect(config.sql["api_dsn"]) as connection:
            assert connection.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False, False, False, False, False)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("CREATE TABLE public.forbidden(id int)")
        command = [sys.executable, str(ROOT / "scripts" / "run_local_server.py"), "--config", result["config_path"], "init"]
        initialized = subprocess.run(command, capture_output=True, text=True, timeout=90)
        assert initialized.returncode == 0, initialized.stdout
        assert json.loads(initialized.stdout)["status"] == "initialized"
        assert Store(config).list_jobs() == []
        native.stop()
        assert native.status() == {"postgres": "stopped", "fuseki": "stopped"}
        assert native.start() == {"postgres": "running", "fuseki": "running"}
        assert Store(config).list_jobs() == []
    finally:
        native.stop()
    assert native.status() == {"postgres": "stopped", "fuseki": "stopped"}
    with pytest.raises(ValueError, match="DATA_NOT_EMPTY"):
        provision_fresh(ROOT, data, tools / "postgresql-17.11" / "bin", tools / "java-21", tools / "fuseki-6.2.0", pg_port=25469, fuseki_port=23069, http_port=8802)
