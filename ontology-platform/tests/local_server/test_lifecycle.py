"""Process ownership must be stronger than a reusable PID."""
import os
from pathlib import Path
import sys

import psutil

from local_server.lifecycle import process_identity, owns_process, atomic_json, load_state, NativeServices, LifecycleError
from types import SimpleNamespace
import pytest
import socket
import httpx


def test_process_ownership_requires_creation_executable_cwd_and_command():
    current = process_identity(os.getpid())
    assert owns_process(current)
    for key, value in [("created", current["created"]-10), ("exe", str(Path(sys.executable).parent / "other.exe")), ("cwd", str(Path.cwd().parent)), ("command", ["unrelated"] )]:
        assert not owns_process({**current, key: value})


def test_state_roundtrip_is_atomic_and_missing_state_is_stopped(tmp_path):
    path = tmp_path / "runtime" / "state.json"
    assert load_state(path) is None
    atomic_json(path, {"owner": "local-server/1", "supervisor": process_identity(os.getpid())})
    assert load_state(path)["owner"] == "local-server/1"
    assert not list(path.parent.glob("*.tmp"))


def test_pending_asset_placement_blocks_service_start_before_any_process_is_spawned(tmp_path,monkeypatch):
    from local_server import lifecycle
    config=SimpleNamespace(root=tmp_path,data_dir=tmp_path,runtime_dir=tmp_path/"runtime",runtime={},
                           config_path=tmp_path/"config.json",host="127.0.0.1",port=8792)
    (tmp_path/"asset-placement.pending.json").write_text('{"status":"pending"}',encoding="utf8")
    monkeypatch.setattr(lifecycle,"_spawn",lambda *args,**kwargs:pytest.fail("pending assets must not start processes"))
    with pytest.raises(LifecycleError,match="资产"):
        lifecycle.start(config)


def test_native_management_requires_matching_deployment_manifest(tmp_path):
    config = SimpleNamespace(root=tmp_path, data_dir=tmp_path/"data", port=8792, runtime={"managed_postgres": True, "pg_port": 25459, "pg_data_dir": str(tmp_path/"data"/"postgres"), "pg_bin": str(tmp_path/"tools")})
    with pytest.raises(LifecycleError): NativeServices(config).validate()
    config.data_dir.mkdir()
    atomic_json(config.data_dir/"deployment.json", {"deployment_id": "synthetic", "root": str(tmp_path), "data_dir": str(config.data_dir), "pg_port": 25449, "http_port":8792})
    with pytest.raises(LifecycleError): NativeServices(config).validate()


def test_external_native_services_are_never_adopted(tmp_path):
    config = SimpleNamespace(root=tmp_path, data_dir=tmp_path/"data", runtime={}, port=8792)
    native = NativeServices(config)
    assert native.status() == {"postgres": "external", "fuseki": "external"}
    assert native.start() == {"postgres": "external", "fuseki": "external"}
    native.stop()


def test_owned_postgres_rejects_connections_pointing_to_another_cluster(tmp_path):
    tools, pg = tmp_path/"tools", tmp_path/"data"/"postgres"
    tools.mkdir(); pg.mkdir(parents=True)
    for name in ("pg_ctl","postgres"):
        (tools/(name+(".exe" if os.name == "nt" else ""))).touch()
    (pg/"PG_VERSION").write_text("17",encoding="ascii")
    atomic_json(tmp_path/"data"/"deployment.json",{"deployment_id":"test-ports","root":str(tmp_path),"data_dir":str(tmp_path/"data"),"pg_port":25459,"http_port":8792})
    config = SimpleNamespace(root=tmp_path,data_dir=tmp_path/"data",port=8792,
        sql={"admin_dsn":"postgresql://admin@127.0.0.1:25449/original"},
        runtime={"managed_postgres":True,"pg_port":25459,"pg_data_dir":str(pg),"pg_bin":str(tools)})
    with pytest.raises(LifecycleError):
        NativeServices(config).validate()


def test_owned_fuseki_config_cannot_open_tdb_outside_its_data_directory(tmp_path):
    root = Path(__file__).resolve().parents[2]
    rdf = tmp_path/"fuseki"
    rdf.mkdir()
    java_home, fuseki_home = tmp_path/"java",tmp_path/"tools"
    (java_home/"bin").mkdir(parents=True)
    fuseki_home.mkdir()
    (java_home/"bin"/("java.exe" if os.name == "nt" else "java")).touch()
    (fuseki_home/"fuseki-server.jar").touch()
    (rdf/"config.ttl").write_text('@prefix tdb2: <http://jena.apache.org/2016/tdb#> . <#d> a tdb2:DatasetTDB2; tdb2:location "../outside" .',encoding="utf8")
    atomic_json(tmp_path/"deployment.json",{"deployment_id":"test-path","root":str(root),"data_dir":str(tmp_path),"fuseki_port":23059,"http_port":8792})
    config = SimpleNamespace(root=root,data_dir=tmp_path,port=8792,fuseki_url="http://127.0.0.1:23059/fish_l1",runtime={"managed_fuseki":True,"fuseki_port":23059,"fuseki_state_dir":str(rdf),"java_home":str(java_home),"fuseki_home":str(fuseki_home)})
    with pytest.raises((LifecycleError,ValueError)):
        NativeServices(config).validate()


@pytest.fixture
def synthetic_fuseki_identity(tmp_path, monkeypatch):
    """Real manifest/config validation; only external process inspection is fake."""
    from local_server import lifecycle
    root, data = tmp_path / 'project', tmp_path / 'data'
    rdf, java_home, fuseki_home = data / 'fuseki', root / 'java', root / 'tools'
    rdf.mkdir(parents=True)
    (java_home / 'bin').mkdir(parents=True)
    fuseki_home.mkdir()
    (java_home / 'bin' / ('java.exe' if os.name == 'nt' else 'java')).touch()
    (fuseki_home / 'fuseki-server.jar').touch()
    runner = root / 'infra/local-server/LocalFusekiRunner.java'
    runner.parent.mkdir(parents=True)
    runner.touch()
    (rdf / 'config.ttl').write_text('@prefix tdb2: <http://jena.apache.org/2016/tdb#> . <#d> a tdb2:DatasetTDB2; tdb2:location "databases/test" .', encoding='utf-8')
    atomic_json(data / 'deployment.json', {'deployment_id': 'test-pid-reuse', 'root': str(root),
        'data_dir': str(data), 'fuseki_port': 24198, 'http_port': 8898})
    config = SimpleNamespace(root=root, data_dir=data, port=8898, fuseki_url='http://127.0.0.1:24198/test',
        runtime={'managed_fuseki': True, 'fuseki_port': 24198, 'fuseki_state_dir': str(rdf),
                 'java_home': str(java_home), 'fuseki_home': str(fuseki_home)})
    native = NativeServices(config)
    native.validate()
    saved = {'pid': 12345, 'created': 100.0, 'exe': str(native.java), 'cwd': str(rdf),
             'command': [str(native.java), '--class-path', str(native.jar), str(runner),
                         str(native.rdf_config), '24198'], 'deployment_id': 'test-pid-reuse'}
    atomic_json(rdf / 'process.json', saved)
    actual = {key: value for key, value in saved.items() if key != 'deployment_id'}
    monkeypatch.setattr(lifecycle.psutil, 'pid_exists', lambda pid: pid == saved['pid'])
    monkeypatch.setattr(lifecycle, 'process_identity', lambda pid: dict(actual))
    return native, saved, actual


def test_recycled_fuseki_pid_is_stale_without_adopting_or_stopping_the_new_process(synthetic_fuseki_identity, monkeypatch):
    from local_server import lifecycle
    native, saved, actual = synthetic_fuseki_identity
    actual.update(created=200.0, exe='unrelated.exe', cwd='unrelated', command=['unrelated'])
    monkeypatch.setattr(lifecycle, 'owns_process', lambda identity: pytest.fail('a recycled PID must not be stopped'))
    assert native._rdf_identity() is None
    native.stop()
    assert not (native.rdf_dir / 'graceful-stop.request').exists()
    assert not (native.rdf_dir / 'process.json').exists()


@pytest.mark.parametrize('occupied', [False, True])
def test_recycled_fuseki_pid_still_requires_a_free_port_before_new_launch(synthetic_fuseki_identity, monkeypatch, occupied):
    from local_server import lifecycle
    native, _, actual = synthetic_fuseki_identity
    actual.update(created=200.0, exe='unrelated.exe', cwd='unrelated', command=['unrelated'])
    monkeypatch.setattr(lifecycle, '_port_open', lambda port: occupied)

    class NewLaunchRequested(Exception):
        pass

    def launch(*args, **kwargs):
        if occupied:
            pytest.fail('an occupied port must be refused before launching a process')
        raise NewLaunchRequested()

    monkeypatch.setattr(lifecycle.subprocess, 'Popen', launch)
    if occupied:
        with pytest.raises(LifecycleError) as error:
            native.start()
        assert error.value.code == 'FUSEKI_PORT_IN_USE'
    else:
        with pytest.raises(NewLaunchRequested):
            native.start()


@pytest.mark.parametrize('field,value', [('exe', 'unrelated.exe'), ('cwd', 'unrelated'),
                                        ('command', ['unrelated']), ('deployment_id', 'other-deployment')])
def test_same_lifetime_fuseki_identity_mismatch_remains_rejected(synthetic_fuseki_identity, monkeypatch, field, value):
    from local_server import lifecycle
    native, saved, actual = synthetic_fuseki_identity
    if field == 'deployment_id':
        atomic_json(native.rdf_dir / 'process.json', {**saved, field: value})
    else:
        actual[field] = value
    monkeypatch.setattr(lifecycle, 'owns_process', lambda identity: pytest.fail('foreign process must not be stopped'))
    with pytest.raises(LifecycleError) as error:
        native.stop()
    assert error.value.code == 'FUSEKI_FOREIGN_PROCESS'
    assert (native.rdf_dir / 'process.json').is_file()
    assert not (native.rdf_dir / 'graceful-stop.request').exists()


@pytest.mark.parametrize('replace_record', [False, True])
def test_graceful_fuseki_stop_removes_only_the_unchanged_process_record(synthetic_fuseki_identity, monkeypatch, replace_record):
    from local_server import lifecycle
    native, saved, _ = synthetic_fuseki_identity
    replacement = {**saved, 'pid': 54321, 'created': 200.0}

    def exited(identity):
        if replace_record:
            atomic_json(native.rdf_dir / 'process.json', replacement)
        return False

    monkeypatch.setattr(lifecycle, 'owns_process', exited)
    native.stop()
    assert (native.rdf_dir / 'graceful-stop.request').read_text(encoding='utf-8') == 'test-pid-reuse'
    if replace_record:
        assert load_state(native.rdf_dir / 'process.json') == replacement
    else:
        assert not (native.rdf_dir / 'process.json').exists()


@pytest.mark.skipif(not os.environ.get("LOCAL_SERVER_NATIVE_TEST_JAVA_HOME"), reason="requires explicitly supplied local Java21/Fuseki6.2.0 fixture tools")
def test_native_fuseki_graceful_stop_and_reopen_persists_triples(tmp_path):
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1",0))
        port = port_probe.getsockname()[1]
    root = Path(__file__).resolve().parents[2]
    rdf = tmp_path/"fuseki"
    rdf.mkdir()
    (rdf/"config.ttl").write_text('@prefix fuseki: <http://jena.apache.org/fuseki#> . @prefix tdb2: <http://jena.apache.org/2016/tdb#> . <#s> a fuseki:Service; fuseki:name "fixture"; fuseki:endpoint [fuseki:operation fuseki:query; fuseki:name "query"]; fuseki:endpoint [fuseki:operation fuseki:update; fuseki:name "update"]; fuseki:dataset <#d> . <#d> a tdb2:DatasetTDB2; tdb2:location "databases/fixture" .',encoding="utf-8")
    atomic_json(tmp_path/"deployment.json",{"deployment_id":"test-graceful","root":str(root),"data_dir":str(tmp_path),"fuseki_port":port,"http_port":8792})
    config = SimpleNamespace(root=root, data_dir=tmp_path, port=8792, fuseki_url=f"http://127.0.0.1:{port}/fixture", runtime={"managed_fuseki":True,"fuseki_state_dir":str(rdf),"fuseki_port":port,"java_home":os.environ["LOCAL_SERVER_NATIVE_TEST_JAVA_HOME"],"fuseki_home":os.environ["LOCAL_SERVER_NATIVE_TEST_FUSEKI_HOME"]})
    native = NativeServices(config)
    try:
        assert native.start()["fuseki"] == "running"
        with httpx.Client(trust_env=False,timeout=10) as client:
            assert client.post(config.fuseki_url+"/update",data={"update":"INSERT DATA { <urn:test:s> <urn:test:p> <urn:test:o> }"}).status_code in (200, 204)
        native.stop()
        assert native.status()["fuseki"] == "stopped"
        native.start()
        with httpx.Client(trust_env=False,timeout=10) as client:
            result = client.post(config.fuseki_url+"/query",data={"query":"ASK { <urn:test:s> <urn:test:p> <urn:test:o> }"},headers={"Accept":"application/sparql-results+json"})
            assert result.json()["boolean"] is True
    finally:
        native.stop()
