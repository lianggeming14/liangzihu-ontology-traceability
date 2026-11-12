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
