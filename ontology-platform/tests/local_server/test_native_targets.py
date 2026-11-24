"""Native regression safety checks run without opening any real connection."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def inputs(tmp_path):
    manifest = {
        "contract": "lzo-native-test-targets/1", "synthetic_only": True,
        "fixture_id": "regression_20261123",
        "postgres": {
            "source": {"port": 25591, "data_dir": str(tmp_path / "source")},
            "restore": {"port": 25592, "data_dir": str(tmp_path / "restore")},
        },
        "fuseki": {"port": 23191, "state_dir": str(tmp_path / "fuseki"), "dataset": "test_regression"},
        "pg_bin": str(tmp_path / "pg_bin"),
    }
    env = {"LZO_NATIVE_TEST_MANIFEST": str(tmp_path / "targets.json")}
    for role in ("ADMIN", "API", "WORKER"):
        env[f"LZO_LOCAL_TEST_{role}_DATABASE_URL"] = f"host=127.0.0.1 port=25591 dbname=test_regression user={role.lower()} password=secret_sentinel"
    env["LZO_LOCAL_TEST_RESTORE_ADMIN_DATABASE_URL"] = "host=127.0.0.1 port=25592 dbname=test_restore user=restore password=secret_sentinel"
    for path in (manifest["postgres"]["source"]["data_dir"], manifest["postgres"]["restore"]["data_dir"], manifest["fuseki"]["state_dir"], manifest["pg_bin"]):
        Path(path).mkdir()
    return manifest, env


def load(inputs):
    from native_targets import NativeTargets
    manifest, env = inputs
    Path(env["LZO_NATIVE_TEST_MANIFEST"]).write_text(json.dumps(manifest), encoding="utf-8")
    return NativeTargets.from_environment(env)


@pytest.mark.parametrize("port", [25459, 25449, 23059, 23049])
def test_protected_target_is_rejected_before_connect(inputs, port):
    from native_targets import NativeTargetError
    manifest, env = inputs
    manifest["postgres"]["source"]["port"] = port
    for role in ("ADMIN", "API", "WORKER"):
        key = f"LZO_LOCAL_TEST_{role}_DATABASE_URL"
        env[key] = env[key].replace("25591", str(port))
    with pytest.raises(NativeTargetError, match="protected"):
        load(inputs)


@pytest.mark.parametrize("replacement", [
    "host=127.0.0.1 port=25592 dbname=test_regression user=api",
    "host=127.0.0.1 port=25591 dbname=test_other user=api",
    "host=example.com port=25591 dbname=test_regression user=api",
    "host=127.0.0.1,127.0.0.2 port=25591 dbname=test_regression user=api",
    "host=127.0.0.1 port=25591 dbname=test_regression user=api hostaddr=127.0.0.1",
    "host=127.0.0.1 port=25591 dbname=test_regression user=api service=hidden",
    "host=127.0.0.1 port=25591 dbname=test_regression user=api options='-c search_path=public'",
])
def test_mixed_or_indirect_role_target_is_rejected(inputs, replacement):
    from native_targets import NativeTargetError
    inputs[1]["LZO_LOCAL_TEST_API_DATABASE_URL"] = replacement
    with pytest.raises(NativeTargetError):
        load(inputs)


@pytest.mark.parametrize("mutate", [
    lambda m: m.update(synthetic_only=False),
    lambda m: m.update(contract="other"),
    lambda m: m.update(fixture_id="../escape"),
    lambda m: m["postgres"]["restore"].update(port=25591),
    lambda m: m["postgres"]["restore"].update(data_dir=m["postgres"]["source"]["data_dir"]),
    lambda m: m["postgres"]["restore"].update(data_dir=str(Path(m["postgres"]["source"]["data_dir"]) / "nested")),
    lambda m: m["fuseki"].update(port=23059),
    lambda m: m["fuseki"].update(dataset="business"),
    lambda m: m["fuseki"].update(dataset="test_a/../../fish_l1"),
    lambda m: m.update(pg_bin="relative"),
    lambda m: m.update(password="manifest_must_not_have_credentials"),
])
def test_manifest_must_describe_separate_explicit_synthetic_targets(inputs, mutate):
    from native_targets import NativeTargetError
    mutate(inputs[0])
    with pytest.raises(NativeTargetError):
        load(inputs)


def test_manifest_and_explicit_test_database_are_required(inputs):
    from native_targets import NativeTargetError, NativeTargets
    with pytest.raises(NativeTargetError):
        NativeTargets.from_environment({})
    inputs[1]["LZO_LOCAL_TEST_ADMIN_DATABASE_URL"] = inputs[1]["LZO_LOCAL_TEST_ADMIN_DATABASE_URL"].replace("test_regression", "lzo")
    with pytest.raises(NativeTargetError):
        load(inputs)


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
def test_libpq_environment_cannot_redirect_explicit_target(inputs, key):
    from native_targets import NativeTargetError
    inputs[1][key] = "indirect"
    with pytest.raises(NativeTargetError):
        load(inputs)


def test_dsn_errors_and_repr_do_not_expose_credentials(inputs):
    from native_targets import NativeTargetError
    secret = "_".join(("secret", "sentinel"))
    targets = load(inputs)
    assert secret not in repr(targets)
    inputs[1]["LZO_LOCAL_TEST_API_DATABASE_URL"] = "password='" + secret
    with pytest.raises(NativeTargetError) as error:
        load(inputs)
    assert secret not in str(error.value)
    assert secret not in str(error.getrepr(style="long"))


class ProbeConnection:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.queries = []
        self.closed = False

    def execute(self, statement):
        self.queries.append(statement)
        assert statement == "SHOW data_directory", "identity probe must never execute DDL"
        return self

    def fetchone(self):
        return (self.data_dir,)

    def close(self):
        self.closed = True


def test_identity_probe_is_readonly_and_mismatch_prevents_write_access(inputs):
    from native_targets import NativeTargetError
    targets = load(inputs)
    probe = ProbeConnection(str(Path(inputs[0]["postgres"]["source"]["data_dir"]).parent / "wrong"))
    def connect(dsn, **kwargs):
        assert "default_transaction_read_only=on" in kwargs["options"]
        return probe
    with pytest.raises(NativeTargetError, match="data directory"):
        targets.verify_cluster("source", connect=connect)
    assert probe.closed
    assert probe.queries == ["SHOW data_directory"]


def test_matching_identity_probe_accepts_normalized_path_and_closes(inputs):
    targets = load(inputs)
    probe = ProbeConnection(inputs[0]["postgres"]["source"]["data_dir"])
    targets.verify_cluster("source", connect=lambda dsn, **kwargs: probe)
    assert probe.closed
    assert targets.fuseki_url == "http://127.0.0.1:23191/test_regression"


@pytest.mark.parametrize("fixture_name", ["store", "backup", "cross_admin", "worker"])
def test_native_fixture_entry_points_refuse_production_before_any_network(inputs, monkeypatch, tmp_path, fixture_name):
    import psycopg
    from native_targets import NativeTargetError
    manifest, env = inputs
    manifest['postgres']['source']['port'] = 25459
    Path(env['LZO_NATIVE_TEST_MANIFEST']).write_text(json.dumps(manifest), encoding='utf-8')
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('LZO_LOCAL_BACKUP_NATIVE_TESTS', '1')
    monkeypatch.setenv('LZO_LOCAL_BACKUP_XADMIN_TESTS', '1')
    def forbidden_connect(*args, **kwargs):
        pytest.fail('target validation must precede every network connection')
    monkeypatch.setattr(psycopg, 'connect', forbidden_connect)
    if fixture_name == 'store':
        from test_store import stores
        fixture = stores.__wrapped__(tmp_path)
    elif fixture_name == 'backup':
        from test_backup import native_fixture
        fixture = native_fixture.__wrapped__()
    elif fixture_name == 'cross_admin':
        from test_backup import xadmin_fixture
        fixture = xadmin_fixture.__wrapped__(tmp_path)
    else:
        from test_worker import native_import_fixture
        fixture = native_import_fixture.__wrapped__(monkeypatch)
    with pytest.raises(NativeTargetError, match='protected'):
        next(fixture)


def test_database_cleanup_only_drops_the_database_created_by_this_context(inputs, monkeypatch):
    from native_targets import NativeTargets
    targets = load(inputs)
    statements = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, statement):
            statements.append(statement.as_string())
    monkeypatch.setattr(NativeTargets, 'connect_admin', lambda *args, **kwargs: Connection())
    with pytest.raises(RuntimeError, match='synthetic failure'):
        with targets.database('guard') as (database, dsns):
            assert database.startswith('test_guard_')
            assert 'dbname=' + database in dsns['api']
            raise RuntimeError('synthetic failure')
    assert statements == ['CREATE DATABASE "' + database + '"', 'DROP DATABASE "' + database + '"']
    assert 'test_regression' not in ''.join(statements)


def test_failed_database_creation_does_not_drop_a_preexisting_name(inputs, monkeypatch):
    from native_targets import NativeTargets
    targets = load(inputs)
    statements = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, statement):
            statements.append(statement.as_string())
            raise RuntimeError('database already exists')
    monkeypatch.setattr(NativeTargets, 'connect_admin', lambda *args, **kwargs: Connection())
    with pytest.raises(RuntimeError, match='already exists'):
        with targets.database('guard'):
            pytest.fail('must not yield access when database creation fails')
    assert len(statements) == 1
    assert statements[0].startswith('CREATE DATABASE "test_guard_')


@pytest.fixture
def rdf_identity(inputs):
    targets = load(inputs)
    state = targets.fuseki_state_dir
    (state / 'config.ttl').write_text('''@prefix fuseki: <http://jena.apache.org/fuseki#> .
@prefix tdb2: <http://jena.apache.org/2016/tdb#> .
<#service> a fuseki:Service; fuseki:name "test_regression"; fuseki:dataset <#dataset> .
<#dataset> a tdb2:DatasetTDB2; tdb2:location "databases/test_regression" .
''', encoding='utf-8')
    identity = {'pid': 1234, 'created': 100.0, 'exe': str(state.parent / 'java.exe'),
                'cwd': str(state), 'command': ['java', 'LocalFusekiRunner.java', str(state / 'config.ttl'), '23191', 'stop', 'fixture'],
                'listening_ports': [23191]}
    (state / 'process.json').write_text(json.dumps(identity), encoding='utf-8')
    return targets, identity


def test_fuseki_identity_matches_live_process_configuration_and_dataset(rdf_identity):
    targets, identity = rdf_identity
    targets.verify_fuseki(inspect_process=lambda pid: identity)


def test_real_process_inspector_reads_only_the_calling_process():
    import os
    from native_targets import _inspect_fuseki_process
    identity = _inspect_fuseki_process(os.getpid())
    assert identity['pid'] == os.getpid()
    assert identity['command']
    assert isinstance(identity['listening_ports'], list)


@pytest.mark.parametrize('field,value', [
    ('created', 200.0), ('cwd', '/another-state'), ('listening_ports', [23059]),
    ('command', ['java', 'LocalFusekiRunner.java', '/wrong/config.ttl', '23191']),
])
def test_fuseki_wrong_live_process_identity_is_rejected(rdf_identity, field, value):
    from native_targets import NativeTargetError
    targets, identity = rdf_identity
    identity[field] = value
    with pytest.raises(NativeTargetError, match='Fuseki identity'):
        targets.verify_fuseki(inspect_process=lambda pid: identity)


@pytest.mark.parametrize('before,after', [('test_regression', 'fish_l1'), ('databases/test_regression', '../../outside')])
def test_fuseki_config_must_bind_the_declared_dataset_inside_its_state(rdf_identity, before, after):
    from native_targets import NativeTargetError
    targets, identity = rdf_identity
    config = targets.fuseki_state_dir / 'config.ttl'
    config.write_text(config.read_text(encoding='utf-8').replace(before, after), encoding='utf-8')
    with pytest.raises(NativeTargetError, match='Fuseki identity'):
        targets.verify_fuseki(inspect_process=lambda pid: identity)


@pytest.mark.parametrize('scenario', ['created', 'upload_failed_before_creation', 'delete_without_removing'])
def test_worker_fixture_cleans_only_owned_graphs_and_verifies_absence(inputs, monkeypatch, tmp_path, scenario):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from urllib.parse import parse_qs
    import re
    import httpx
    from local_server import worker
    from native_targets import NativeTargetError, NativeTargets
    import test_worker

    targets = load(inputs)
    monkeypatch.setattr(NativeTargets, 'from_environment', lambda: targets)
    monkeypatch.setattr(NativeTargets, 'verify_cluster', lambda *args: None)
    monkeypatch.setattr(NativeTargets, 'verify_fuseki', lambda *args: None)
    monkeypatch.setattr(test_worker, 'ROOT', tmp_path)

    @contextmanager
    def database(*args):
        yield 'test_worker_owned', {}

    monkeypatch.setattr(NativeTargets, 'database', database)
    graphs = {'urn:test:preexisting'}
    owned = 'urn:test:owned'

    def upload(config, generated, **kwargs):
        if scenario == 'upload_failed_before_creation':
            raise RuntimeError('synthetic upload failure')
        graphs.add(generated['graph_iri'])

    monkeypatch.setattr(worker, 'load_and_verify', upload)

    def transport(request):
        if request.method == 'POST' and request.url.path == '/test_regression/query':
            query = parse_qs(request.content.decode())['query'][0]
            graph = re.search(r'GRAPH <([^>]+)>', query).group(1)
            return httpx.Response(200, json={'boolean': graph in graphs})
        if request.method == 'DELETE' and request.url.path == '/test_regression/data':
            graph = request.url.params['graph']
            assert graph == owned, 'cleanup must never remove a preexisting graph'
            if graph not in graphs:
                return httpx.Response(404)
            if scenario != 'delete_without_removing':
                graphs.remove(graph)
            return httpx.Response(204)
        pytest.fail('fixture must use only graph query/data endpoints')

    client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(transport), **kwargs))
    fixture = test_worker.native_import_fixture.__wrapped__(monkeypatch)
    _, _, _, build_dir = next(fixture)
    if scenario == 'upload_failed_before_creation':
        with pytest.raises(RuntimeError, match='synthetic upload failure'):
            worker.load_and_verify(SimpleNamespace(), {'graph_iri': owned})
    else:
        worker.load_and_verify(SimpleNamespace(), {'graph_iri': owned})
    if scenario == 'delete_without_removing':
        with pytest.raises(NativeTargetError, match='graph cleanup'):
            next(fixture)
    else:
        with pytest.raises(StopIteration):
            next(fixture)
        assert graphs == {'urn:test:preexisting'}
    evidence = json.loads((build_dir / 'fixture-cleanup.json').read_text(encoding='utf-8'))
    assert evidence['rdf_cleanup_verified'] is (scenario != 'delete_without_removing')
