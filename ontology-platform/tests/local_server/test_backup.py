from contextlib import contextmanager
import copy
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from local_server.backup import BackupError, create_backup, restore_backup, verify_backup


SOURCE_RDF = b'<urn:s> <urn:p> "01"^^<urn:integer> .\n_:a <urn:p> "asset" <urn:history> .\n_:a <urn:q> <urn:s> <urn:active> .\n'


@pytest.fixture
def dataset():
    state = {'source': SOURCE_RDF, 'target': b''}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            data = state[self.path.split('/')[1]]
            self.send_response(200)
            self.send_header('Content-Type', 'application/n-quads')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.headers.get('Transfer-Encoding') == 'chunked':
                chunks = []
                while True:
                    length = int(self.rfile.readline().strip(), 16)
                    if not length:
                        self.rfile.readline()
                        break
                    chunks.append(self.rfile.read(length))
                    self.rfile.read(2)
                data = b''.join(chunks)
            else:
                data = self.rfile.read(int(self.headers['Content-Length']))
            state['target'] = data
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', state
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class FixturePostgres:
    """Small logical-archive fixture; HTTP/filesystem/integrity remain real."""
    def __init__(self):
        self.restored = {}
        self.expected = {'schemas': ['csv_batch_a4d78be79a83', 'fish_review_10pct_v1', 'lzo_local', 'public'], 'extensions': [{'name': 'postgis', 'version': '3.5'}], 'tables': [{'schema': 'csv_batch_a4d78be79a83', 'name': 'Fish', 'columns': [{'name': 'ID', 'type': 'integer'}], 'row_count': 2, 'row_sha256': 'fixture-rows'}], 'roles': [{'name': 'owner', 'login': False}], 'server_version': '17.5'}

    @contextmanager
    def hold_sources(self, databases):
        yield {name: 'fixture-snapshot' for name in databases}

    def capture(self, name, dsn, path, snapshot):
        path.write_bytes(json.dumps(self.expected).encode())
        return copy.deepcopy(self.expected)

    def assert_empty(self, name, dsn):
        if name in self.restored:
            raise BackupError('RESTORE_SQL_TARGET_NOT_EMPTY')

    def restore(self, name, dsn, path, *, inventory=None):
        self.restored[name] = json.loads(path.read_bytes())

    def inventory(self, name, dsn):
        return self.restored[name]

    def prepare_roles(self, dsn, inventories, *, provision=False):
        return {'created': [], 'required': []}


def source_options(base, backend, asset):
    return {'databases': {name: f'host=127.0.0.1 port=25449 dbname={name} user=backup password=PRIVATE_SENTINEL' for name in ('lzo', 'lzo_gis', 'lzo_timeseries', 'lzo_catalog')}, 'source_dataset': base + '/source', 'pg_bin': '.', 'assets': {'navigation': asset}, 'writers_stopped': True, '_postgres': backend, 'minimum_free_bytes': 0}


def test_complete_backup_restore_includes_all_databases_schemas_graphs_and_assets(tmp_path, dataset):
    base, state = dataset
    backend = FixturePostgres()
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'ontology.owl').write_text('owl content')
    config = SimpleNamespace(data_dir=tmp_path / 'new-data')
    manifest = create_backup(config, tmp_path / 'backup', source_options=source_options(base, backend, assets))
    report = verify_backup(manifest)
    assert report['status'] == 'verified'
    saved = json.loads(manifest.read_text())
    assert set(saved['databases']) == {'lzo', 'lzo_gis', 'lzo_timeseries', 'lzo_catalog'}
    assert 'csv_batch_a4d78be79a83' in saved['databases']['lzo']['inventory']['schemas']
    assert saved['rdf']['inventory']['quad_count'] == 3
    assert {g['graph'] for g in saved['rdf']['inventory']['named_graphs']} == {'<urn:history>', '<urn:active>'}
    assert 'PRIVATE_SENTINEL' not in manifest.read_text()
    restored = restore_backup(config, manifest, target_options={'databases': {name: f'host=127.0.0.1 port=25459 dbname={name} user=restore' for name in saved['databases']}, 'target_dataset': base + '/target', 'pg_bin': '.', '_postgres': backend, 'asset_destination': tmp_path / 'restored-assets', 'minimum_free_bytes': 0})
    assert restored['status'] == 'restored_verified'
    assert state['target'] == SOURCE_RDF
    assert (tmp_path / 'restored-assets/navigation/ontology.owl').read_text() == 'owl content'


def test_missing_modified_or_escaped_material_is_refused_before_restore(tmp_path, dataset):
    base, _ = dataset
    asset = tmp_path / 'map.json'
    asset.write_text('{}')
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options=source_options(base, FixturePostgres(), asset))
    saved = json.loads(manifest.read_text())
    archive = manifest.parent / saved['rdf']['file']
    archive.write_bytes(archive.read_bytes()[:-5])
    with pytest.raises(BackupError, match='HASH|SIZE|INTEGRITY'):
        verify_backup(manifest)
    saved['rdf']['file'] = '../map.json'
    manifest.write_text(json.dumps(saved))
    with pytest.raises(BackupError, match='PATH'):
        verify_backup(manifest)


def test_restore_refuses_original_sql_or_rdf_and_nonempty_targets(tmp_path, dataset):
    base, state = dataset
    backend = FixturePostgres()
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    options = source_options(base, backend, asset)
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options=options)
    targets = {'databases': {name: dsn.replace('25449', '25459') for name, dsn in options['databases'].items()}, 'target_dataset': base + '/target', '_postgres': backend, 'pg_bin': '.', 'asset_destination': tmp_path / 'restore', 'minimum_free_bytes': 0}
    with pytest.raises(BackupError, match='SAME_SOURCE'):
        restore_backup(SimpleNamespace(), manifest, target_options={**targets, 'databases': options['databases']})
    with pytest.raises(BackupError, match='SAME_SOURCE'):
        restore_backup(SimpleNamespace(), manifest, target_options={**targets, 'target_dataset': base + '/source'})
    state['target'] = b'<urn:existing> <urn:p> "keep" .\n'
    with pytest.raises(BackupError, match='NOT_EMPTY'):
        restore_backup(SimpleNamespace(), manifest, target_options=targets)
    assert backend.restored == {}


def test_writers_and_secrets_or_symlink_assets_are_refused(tmp_path, dataset):
    base, _ = dataset
    secret = tmp_path / 'services.env'
    secret.write_text('PASSWORD=PRIVATE_SENTINEL')
    options = source_options(base, FixturePostgres(), secret)
    with pytest.raises(BackupError, match='WRITERS'):
        create_backup(SimpleNamespace(), tmp_path / 'one', source_options={**options, 'writers_stopped': False})
    with pytest.raises(BackupError, match='SECRET'):
        create_backup(SimpleNamespace(), tmp_path / 'two', source_options=options)


def test_restore_rejects_full_readback_mismatch_and_never_reports_success(tmp_path, dataset):
    base, state = dataset
    backend = FixturePostgres()
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options=source_options(base, backend, asset))
    backend.inventory = lambda name, dsn: {**backend.restored[name], 'tables': []}
    with pytest.raises(BackupError, match='FULL_READBACK_MISMATCH'):
        restore_backup(SimpleNamespace(), manifest, target_options={'databases': {name: f'host=localhost port=25459 dbname={name}' for name in ('lzo', 'lzo_gis', 'lzo_timeseries', 'lzo_catalog')}, 'target_dataset': base + '/target', 'pg_bin': '.', '_postgres': backend, 'asset_destination': tmp_path / 'restored', 'minimum_free_bytes': 0})
    assert state['target'] == b''
    failures = list(manifest.parent.glob('restore-failed-*.json'))
    assert len(failures) == 1
    assert json.loads(failures[0].read_text())['status'] == 'failed'


def test_backup_fails_before_capturing_when_space_is_insufficient(tmp_path, dataset):
    base, _ = dataset
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    options = source_options(base, FixturePostgres(), asset)
    with pytest.raises(BackupError, match='DISK_SPACE'):
        create_backup(SimpleNamespace(), tmp_path / 'backup', source_options={**options, 'minimum_free_bytes': 2**63})
    assert not (tmp_path / 'backup/manifest.json').exists()


def test_backup_refuses_destination_inside_asset_tree(tmp_path, dataset):
    base, _ = dataset
    asset = tmp_path / 'raw'
    asset.mkdir()
    (asset / 'data.csv').write_text('ID\n1\n')
    with pytest.raises(BackupError, match='OVERLAP'):
        create_backup(SimpleNamespace(), asset / 'backup', source_options=source_options(base, FixturePostgres(), asset))


def test_restore_refuses_source_dataset_hidden_behind_dot_segments(tmp_path, dataset):
    base, _ = dataset
    backend = FixturePostgres()
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options=source_options(base, backend, asset))
    with pytest.raises(BackupError, match='DATASET|SAME_SOURCE'):
        restore_backup(SimpleNamespace(), manifest, target_options={'databases': {name: f'host=127.0.0.1 port=25459 dbname={name}' for name in ('lzo', 'lzo_gis', 'lzo_timeseries', 'lzo_catalog')}, 'target_dataset': base + '/target/../source', 'pg_bin': '.', '_postgres': backend, 'asset_destination': tmp_path / 'restored'})


_ARRAY_CHECK = "CHECK (decision::text = ANY (ARRAY['approve'::character varying, 'reject'::character varying]::text[]))"
_ELEMENT_CHECK = "CHECK (decision::text = ANY (ARRAY['approve'::character varying::text, 'reject'::character varying::text]))"


def _inventory_with_check(definition):
    return {'schemas': ['public'], 'tables': [{'schema': 'public', 'name': 'decision', 'columns': [{'name': 'decision', 'type': 'character varying'}], 'constraints': [{'name': 'decision_check', 'definition': definition}], 'row_count': 1, 'row_sha256': 'fixture-hash'}]}


def test_comparison_accepts_only_builtin_varchar_literal_array_text_rewrite():
    from local_server.backup import _comparable_inventory
    original = _inventory_with_check(_ARRAY_CHECK)
    restored = _inventory_with_check(_ELEMENT_CHECK)
    assert _comparable_inventory(original) == _comparable_inventory(restored)
    assert original['tables'][0]['constraints'][0]['definition'] == _ARRAY_CHECK
    for changed in (_ELEMENT_CHECK.replace("'approve'", "'delete'"), _ELEMENT_CHECK.replace('::text]', '::name]'), _ELEMENT_CHECK.replace('::text,', '::varchar,')):
        assert _comparable_inventory(original) != _comparable_inventory(_inventory_with_check(changed))


@pytest.mark.parametrize('wrapper', [lambda s: "CHECK (note = '" + s.replace("'", "''") + "')", lambda s: 'CHECK ("' + s.replace('"', '""') + '" IS NULL)', lambda s: 'CHECK (note = $quoted$' + s + '$quoted$)', lambda s: "CHECK (note = E'\\'" + s.replace("'", "\\'") + "')"])
def test_constraint_normalization_never_rewrites_quoted_sql_payload(wrapper):
    from local_server.backup import _comparable_inventory
    assert _comparable_inventory(_inventory_with_check(wrapper(_ARRAY_CHECK))) != _comparable_inventory(_inventory_with_check(wrapper(_ELEMENT_CHECK)))


def test_constraint_tokenizer_preserves_operator_boundaries():
    from local_server.backup import _comparable_inventory
    assert _comparable_inventory(_inventory_with_check('CHECK (a @> b)')) != _comparable_inventory(_inventory_with_check('CHECK (a @ > b)'))


def test_resume_skips_only_complete_verified_sql_and_rdf_targets(tmp_path, dataset):
    base, state = dataset
    backend = FixturePostgres()
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    options = source_options(base, backend, asset)
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options=options)
    saved = json.loads(manifest.read_text())
    names = sorted(saved['databases'])
    backend.restored[names[0]] = copy.deepcopy(backend.expected)
    existing = backend.restored[names[0]]
    state['target'] = SOURCE_RDF
    existing_rdf = state['target']
    targets = {'databases': {name: dsn.replace('25449', '25459') for name, dsn in options['databases'].items()}, 'target_dataset': base + '/target', '_postgres': backend, 'pg_bin': '.', 'asset_destination': tmp_path / 'assets', 'minimum_free_bytes': 0}
    with pytest.raises(BackupError, match='NOT_EMPTY'):
        restore_backup(SimpleNamespace(), manifest, target_options=targets)
    report = restore_backup(SimpleNamespace(), manifest, target_options={**targets, 'resume_verified_targets': True})
    assert report['status'] == 'restored_verified'
    assert report['resumed_verified_databases'] == [names[0]]
    assert report['databases'][names[0]]['status'] == 'full_readback_verified'
    assert report['databases'][names[0]]['restore_action'] == 'resumed_verified'
    assert report['databases'][names[1]]['restore_action'] == 'pg_restore'
    assert backend.restored[names[0]] is existing
    assert report['rdf_restore_action'] == 'resumed_verified'
    assert state['target'] is existing_rdf


@pytest.mark.parametrize('changed', ['rows', 'columns', 'constraints', 'acl', 'rdf'])
def test_resume_rejects_any_mismatch_before_mutating_other_targets(tmp_path, dataset, changed):
    base, state = dataset
    backend = FixturePostgres()
    backend.expected['tables'][0]['constraints'] = [{'name': 'check', 'definition': _ARRAY_CHECK}]
    backend.expected['schema_security'] = [{'schema': 'public', 'owner': 'owner', 'acl': ['owner=UC/owner']}]
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    options = source_options(base, backend, asset)
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options=options)
    name = sorted(options['databases'])[0]
    backend.restored[name] = copy.deepcopy(backend.expected)
    if changed == 'rows':
        backend.restored[name]['tables'][0]['row_sha256'] = 'changed-row'
    elif changed == 'columns':
        backend.restored[name]['tables'][0]['columns'][0]['type'] = 'text'
    elif changed == 'constraints':
        backend.restored[name]['tables'][0]['constraints'][0]['definition'] = _ELEMENT_CHECK.replace("'approve'", "'delete'")
    elif changed == 'acl':
        backend.restored[name]['schema_security'][0]['acl'] = []
    else:
        state['target'] = b'<urn:wrong> <urn:p> "data" .\n'
    before = copy.deepcopy(backend.restored)
    with pytest.raises(BackupError, match='RESUME.*MISMATCH'):
        restore_backup(SimpleNamespace(), manifest, target_options={'databases': {key: dsn.replace('25449', '25459') for key, dsn in options['databases'].items()}, 'target_dataset': base + '/target', '_postgres': backend, 'pg_bin': '.', 'asset_destination': tmp_path / 'assets', 'minimum_free_bytes': 0, 'resume_verified_targets': True})
    assert backend.restored == before
    assert not (tmp_path / 'assets').exists()


@pytest.fixture
def native_fixture():
    if os.environ.get('LZO_LOCAL_BACKUP_NATIVE_TESTS') != '1':
        pytest.skip('isolated native PostgreSQL fixture is opt-in')
    import psycopg
    from psycopg import sql
    from contextlib import ExitStack
    from native_targets import NativeTargets
    targets = NativeTargets.from_environment()
    targets.verify_cluster('source')
    targets.verify_cluster('restore')
    created_roles = {'source': [], 'restore': []}
    class Fixture:
        def __repr__(self):
            return '<isolated-native-backup-fixture>'
    fixture = Fixture()
    fixture.pg_bin = targets.pg_bin
    fixture.owner = 'lzo_backup_fixture_owner'
    fixture.reader = 'lzo_backup_fixture_reader'
    fixture.created_roles = created_roles['restore']
    fixture.created_source_roles = created_roles['source']
    try:
        for cluster in ('source', 'restore'):
            with targets.connect_admin(cluster, autocommit=True) as connection:
                roles = (fixture.owner, fixture.reader) + (('postgres',) if cluster == 'restore' else ())
                for role in roles:
                    if connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                        pytest.fail('fixture role already exists; refusing to replace it')
                    connection.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role)))
                    created_roles[cluster].append(role)
        with ExitStack() as databases:
            fixture.source_name, source = databases.enter_context(targets.database('backup_source'))
            _, target = databases.enter_context(targets.database('backup_target', cluster='restore'))
            fixture.source, fixture.target = source['admin'], target['admin']
            yield fixture
    finally:
        # Databases are unique per invocation; only successfully created roles
        # are removed. Failure output and files remain in pytest's evidence dir.
        for cluster in ('restore', 'source'):
            if created_roles[cluster]:
                with targets.connect_admin(cluster, autocommit=True) as connection:
                    for role in reversed(created_roles[cluster]):
                        connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_native_snapshot_archive_and_complete_restore(tmp_path, dataset, native_fixture):
    import psycopg
    from psycopg import sql
    from local_server.backup import PostgresArchive
    base, state = dataset
    fixture = native_fixture
    with psycopg.connect(fixture.source) as connection:
        connection.execute('CREATE SCHEMA csv_batch_a4d78be79a83')
        connection.execute('CREATE SCHEMA fish_review_10pct_v1')
        connection.execute('CREATE TYPE public.fixture_kind AS ENUM (\'one\',\'two\')')
        connection.execute('CREATE FUNCTION public.fixture_function() RETURNS integer LANGUAGE sql IMMUTABLE AS \'SELECT 7\'')
        connection.execute('CREATE TABLE csv_batch_a4d78be79a83.parent (id integer PRIMARY KEY, value numeric(12,4), kind public.fixture_kind)')
        connection.execute('INSERT INTO csv_batch_a4d78be79a83.parent VALUES (1,1.2300,\'one\'),(2,NULL,\'two\')')
        connection.execute('CREATE TABLE fish_review_10pct_v1.child (id bigserial PRIMARY KEY, parent_id integer REFERENCES csv_batch_a4d78be79a83.parent(id), text_value text)')
        connection.execute('INSERT INTO fish_review_10pct_v1.child(parent_id,text_value) VALUES (1,\'中文\'),(1,\'literal\')')
        connection.execute('ALTER TABLE csv_batch_a4d78be79a83.parent OWNER TO lzo_backup_fixture_owner')
        connection.execute('GRANT USAGE ON SCHEMA csv_batch_a4d78be79a83 TO lzo_backup_fixture_reader')
        connection.execute('GRANT SELECT ON csv_batch_a4d78be79a83.parent TO lzo_backup_fixture_reader')
        connection.execute('GRANT UPDATE(value) ON csv_batch_a4d78be79a83.parent TO lzo_backup_fixture_reader')
        connection.execute('ALTER FUNCTION public.fixture_function() SECURITY DEFINER')
        connection.execute('ALTER FUNCTION public.fixture_function() OWNER TO lzo_backup_fixture_owner')
        connection.execute('REVOKE ALL ON FUNCTION public.fixture_function() FROM PUBLIC')
        connection.execute('GRANT EXECUTE ON FUNCTION public.fixture_function() TO lzo_backup_fixture_reader')
        connection.execute('GRANT lzo_backup_fixture_reader TO lzo_backup_fixture_owner')
        # Superuser GRANT may be attributed to the cluster's bootstrap role,
        # whose name is independent of the login used by this test. Read the
        # original catalog directly, rather than assuming that name is postgres.
        source_memberships = connection.execute("SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),pg_get_userbyid(grantor),admin_option,inherit_option,set_option FROM pg_auth_members WHERE roleid='lzo_backup_fixture_reader'::regrole AND member='lzo_backup_fixture_owner'::regrole ORDER BY grantor").fetchall()
        assert len(source_memberships) == 1
        source_role, source_member, source_grantor, *source_options = source_memberships[0]
        assert (source_role, source_member, source_options) == (fixture.reader, fixture.owner, [False, True, True])
        assert source_grantor and source_grantor not in (fixture.reader, fixture.owner)
        connection.execute(sql.SQL('ALTER DATABASE {} OWNER TO lzo_backup_fixture_owner').format(sql.Identifier(fixture.source_name)))
        connection.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(fixture.source_name)))
        connection.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO lzo_backup_fixture_reader').format(sql.Identifier(fixture.source_name)))
    backend = PostgresArchive(fixture.pg_bin)
    with backend.hold_sources({'fixture': fixture.source}):
        assert backend.connections['fixture'].execute('SHOW transaction_isolation').fetchone()[0] == 'repeatable read'
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options={'databases': {'fixture': fixture.source}, 'pg_bin': fixture.pg_bin, 'source_dataset': base + '/source', 'assets': {'mapping': asset}, 'writers_stopped': True, 'minimum_free_bytes': 0})
    saved = json.loads(manifest.read_text())['databases']['fixture']['inventory']
    function = next(item for item in saved['routine_security'] if item['name'] == 'fixture_function')
    parent = next(item for item in saved['tables'] if item['name'] == 'parent')
    assert next(item for item in parent['columns'] if item['name'] == 'value')['acl'] == ['lzo_backup_fixture_reader=w/lzo_backup_fixture_owner']
    assert function['owner'] == 'lzo_backup_fixture_owner'
    assert function['security_definer'] is True
    assert function['acl'] == ['lzo_backup_fixture_owner=X/lzo_backup_fixture_owner', 'lzo_backup_fixture_reader=X/lzo_backup_fixture_owner']
    assert saved['role_memberships'] == [{'role': fixture.reader, 'member': fixture.owner, 'grantor': source_grantor, 'admin_option': False, 'inherit_option': True, 'set_option': True}]
    # The restore cluster is independent, so its precreated fixture identities
    # do not already share the source cluster's membership. Provision that
    # membership explicitly, then compare the real grantor and all options.
    result = restore_backup(SimpleNamespace(), manifest, target_options={'databases': {'fixture': fixture.target}, 'pg_bin': fixture.pg_bin, 'target_dataset': base + '/target', 'asset_destination': tmp_path / 'assets', 'minimum_free_bytes': 0, 'provision_roles': True})
    assert result['status'] == 'restored_verified'
    assert result['databases']['fixture']['table_count'] == 2
    assert state['target'] == SOURCE_RDF
    with psycopg.connect(fixture.target) as connection:
        assert connection.execute("SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),pg_get_userbyid(grantor),admin_option,inherit_option,set_option FROM pg_auth_members WHERE roleid='lzo_backup_fixture_reader'::regrole AND member='lzo_backup_fixture_owner'::regrole ORDER BY grantor").fetchall() == source_memberships
        assert connection.execute('SELECT public.fixture_function()').fetchone()[0] == 7
        assert connection.execute("SELECT pg_get_userbyid(proowner),prosecdef,has_function_privilege('lzo_backup_fixture_reader',oid,'EXECUTE'),has_function_privilege('public',oid,'EXECUTE') FROM pg_proc WHERE proname='fixture_function'").fetchone() == ('lzo_backup_fixture_owner', True, True, False)
        assert connection.execute("SELECT pg_get_userbyid(relowner),has_table_privilege('lzo_backup_fixture_reader',oid,'SELECT') FROM pg_class WHERE relname='parent'").fetchone() == ('lzo_backup_fixture_owner', True)
        assert connection.execute('SELECT sum(value)::text FROM csv_batch_a4d78be79a83.parent').fetchone()[0] == '1.2300'
        assert connection.execute('SELECT nextval(\'fish_review_10pct_v1.child_id_seq\')').fetchone()[0] == 3


@pytest.mark.parametrize('statement', ["CREATE FUNCTION public.user_function() RETURNS integer LANGUAGE sql AS 'SELECT 1'", "CREATE TYPE public.user_enum AS ENUM ('keep')"])
def test_native_nonempty_function_or_type_target_is_refused(native_fixture, statement):
    import psycopg
    from local_server.backup import PostgresArchive
    with psycopg.connect(native_fixture.target) as connection:
        connection.execute(statement)
    with pytest.raises(BackupError, match='NOT_EMPTY'):
        PostgresArchive(native_fixture.pg_bin).assert_empty('fixture', native_fixture.target)


def test_native_missing_source_roles_require_explicit_safe_provisioning(native_fixture):
    import psycopg
    from local_server.backup import PostgresArchive
    backend = PostgresArchive(native_fixture.pg_bin)
    name = 'lzo_backup_fixture_provisioned'
    with psycopg.connect(native_fixture.target) as connection:
        grantor = connection.execute('SELECT current_user').fetchone()[0]
        if connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (name,)).fetchone():
            pytest.fail('provision fixture role already exists; refusing to replace it')
    # This tests safe role creation, not an invalid GRANT by the unrelated
    # NOLOGIN source identity precreated on the target. Use its actual admin.
    inventory = {'required_roles': [name, native_fixture.owner, grantor], 'roles': [{'name': name, 'login': True, 'superuser': True, 'createdb': True, 'createrole': True, 'inherit': True}], 'role_memberships': [{'role': name, 'member': native_fixture.owner, 'grantor': grantor, 'admin_option': False, 'inherit_option': True, 'set_option': True}]}
    created = False
    try:
        with pytest.raises(BackupError, match='ROLE'):
            backend.prepare_roles(native_fixture.target, [inventory], provision=False)
        report = backend.prepare_roles(native_fixture.target, [inventory], provision=True)
        created = name in report['created']
        assert report['created'] == [name]
        with psycopg.connect(native_fixture.target) as connection:
            assert connection.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (name,)).fetchone() == (False,False,False,False,False,False)
            assert connection.execute('SELECT pg_has_role(%s,%s,\'MEMBER\')', (native_fixture.owner,name)).fetchone()[0] is True
            assert connection.execute('SELECT pg_get_userbyid(m.grantor),m.admin_option,m.inherit_option,m.set_option FROM pg_auth_members m WHERE pg_get_userbyid(m.roleid)=%s AND pg_get_userbyid(m.member)=%s ORDER BY m.grantor', (name, native_fixture.owner)).fetchall() == [(grantor, False, True, True)]
    finally:
        if created:
            with psycopg.connect(native_fixture.target, autocommit=True) as connection:
                connection.execute('DROP ROLE lzo_backup_fixture_provisioned')


def test_native_postgis_extension_only_target_is_empty_and_restores_exactly(tmp_path, dataset, native_fixture):
    import psycopg
    from local_server.backup import PostgresArchive
    base, _ = dataset
    fixture = native_fixture
    for dsn in (fixture.source, fixture.target):
        with psycopg.connect(dsn) as connection:
            connection.execute('CREATE EXTENSION postgis')
    PostgresArchive(fixture.pg_bin).assert_empty('fixture', fixture.target)
    with psycopg.connect(fixture.source) as connection:
        connection.execute('CREATE TABLE public.fixture_geometry(id integer PRIMARY KEY, geom geometry(Point,4326))')
        connection.execute('INSERT INTO public.fixture_geometry VALUES (1,ST_SetSRID(ST_MakePoint(114.3,30.4),4326))')
    asset = tmp_path / 'model.owl'
    asset.write_text('fixture model')
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options={'databases': {'fixture': fixture.source}, 'pg_bin': fixture.pg_bin, 'source_dataset': base + '/source', 'assets': {'owl': asset}, 'writers_stopped': True, 'minimum_free_bytes': 0})
    result = restore_backup(SimpleNamespace(), manifest, target_options={'databases': {'fixture': fixture.target}, 'pg_bin': fixture.pg_bin, 'target_dataset': base + '/target', 'asset_destination': tmp_path / 'assets', 'minimum_free_bytes': 0})
    assert result['status'] == 'restored_verified'
    with psycopg.connect(fixture.target) as connection:
        assert connection.execute('SELECT ST_AsEWKT(geom) FROM public.fixture_geometry').fetchone()[0] == 'SRID=4326;POINT(114.3 30.4)'


def test_native_check_roundtrip_and_verified_resume_refuse_literal_or_type_changes(tmp_path, dataset, native_fixture):
    import psycopg
    from local_server.backup import PostgresArchive, _canonical_check_definition, _comparable_inventory
    fixture = native_fixture
    base, _ = dataset
    with psycopg.connect(fixture.source) as connection:
        connection.execute('CREATE TABLE public.fixture_decision(decision character varying, CONSTRAINT decision_check ' + _ARRAY_CHECK + ')')
        connection.execute("INSERT INTO public.fixture_decision VALUES ('approve')")
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options={'databases': {'fixture': fixture.source}, 'pg_bin': fixture.pg_bin, 'source_dataset': base + '/source', 'assets': {'mapping': asset}, 'writers_stopped': True, 'minimum_free_bytes': 0})
    expected = json.loads(manifest.read_text())['databases']['fixture']['inventory']
    targets = {'databases': {'fixture': fixture.target}, 'pg_bin': fixture.pg_bin, 'target_dataset': base + '/target', 'asset_destination': tmp_path / 'first-assets', 'minimum_free_bytes': 0}
    first = restore_backup(SimpleNamespace(), manifest, target_options=targets)
    assert first['databases']['fixture']['restore_action'] == 'pg_restore'
    backend = PostgresArchive(fixture.pg_bin)
    actual = backend.inventory('fixture', fixture.target)
    assert _comparable_inventory(actual) == _comparable_inventory(expected)
    source_check = expected['tables'][0]['constraints'][0]['definition']
    target_check = actual['tables'][0]['constraints'][0]['definition']
    # This PostgreSQL parser already emits per-element casts on CREATE TABLE;
    # the production backup supplies the older whole-array spelling. Both
    # spellings must compare to this real pg_dump/pg_restore result.
    assert _canonical_check_definition(source_check) == _canonical_check_definition(_ARRAY_CHECK)
    assert _canonical_check_definition(target_check) == _canonical_check_definition(_ARRAY_CHECK)
    second = restore_backup(SimpleNamespace(), manifest, target_options={**targets, 'asset_destination': tmp_path / 'second-assets', 'resume_verified_targets': True})
    assert second['resumed_verified_databases'] == ['fixture']
    assert second['databases']['fixture']['restore_action'] == 'resumed_verified'
    assert second['rdf_restore_action'] == 'resumed_verified'
    for changed in (_ELEMENT_CHECK.replace("'reject'", "'delete'"), _ELEMENT_CHECK.replace('varying::text', 'varying::name')):
        with psycopg.connect(fixture.target) as connection:
            connection.execute('ALTER TABLE public.fixture_decision DROP CONSTRAINT decision_check')
            connection.execute('ALTER TABLE public.fixture_decision ADD CONSTRAINT decision_check ' + changed)
        with pytest.raises(BackupError, match='RESUME.*MISMATCH'):
            restore_backup(SimpleNamespace(), manifest, target_options={**targets, 'asset_destination': tmp_path / 'refused-assets', 'resume_verified_targets': True})
        with psycopg.connect(fixture.target) as connection:
            assert connection.execute('SELECT decision FROM public.fixture_decision').fetchall() == [('approve',)]
    assert _comparable_inventory(backend.inventory('fixture', fixture.source)) == _comparable_inventory(expected)


def test_native_opt_in_reuses_only_safe_configured_deployment_login_roles(tmp_path, dataset, native_fixture):
    import hashlib
    import secrets
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from local_server.backup import PostgresArchive
    fixture = native_fixture
    base, _ = dataset
    names = ('lzo_backup_fixture_api', 'lzo_backup_fixture_worker')
    passwords = {name: secrets.token_urlsafe(32) for name in names}
    for dsn, created_roles in ((fixture.source, fixture.created_source_roles), (fixture.target, fixture.created_roles)):
        with psycopg.connect(dsn, autocommit=True) as connection:
            for name in names:
                if connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (name,)).fetchone():
                    pytest.fail('deployment fixture role already exists; refusing to replace it')
                connection.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(name), sql.Literal(passwords[name])))
                created_roles.append(name)
    with psycopg.connect(fixture.source) as connection:
        connection.execute('CREATE SCHEMA lzo_local AUTHORIZATION lzo_backup_fixture_api')
        connection.execute('CREATE TABLE lzo_local.fixture_control(id integer PRIMARY KEY, value text)')
        connection.execute("INSERT INTO lzo_local.fixture_control VALUES(1,'restored control metadata')")
        connection.execute('ALTER TABLE lzo_local.fixture_control OWNER TO lzo_backup_fixture_api')
        connection.execute('GRANT USAGE ON SCHEMA lzo_local TO lzo_backup_fixture_worker')
        connection.execute('GRANT SELECT ON lzo_local.fixture_control TO lzo_backup_fixture_worker')
    with psycopg.connect(fixture.target) as connection:
        before = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in connection.execute('SELECT rolname,rolpassword FROM pg_authid WHERE rolname=ANY(%s)', (list(names),))}
    api_dsn = make_conninfo(fixture.target, user=names[0], password=passwords[names[0]])
    worker_dsn = make_conninfo(fixture.target, user=names[1], password=passwords[names[1]])
    config = SimpleNamespace(sql={'api_dsn': api_dsn, 'worker_dsn': worker_dsn})
    asset = tmp_path / 'mapping.json'
    asset.write_text('{}')
    manifest = create_backup(config, tmp_path / 'backup', source_options={'databases': {'fixture': fixture.source}, 'pg_bin': fixture.pg_bin, 'source_dataset': base + '/source', 'assets': {'mapping': asset}, 'writers_stopped': True, 'minimum_free_bytes': 0})
    targets = {'databases': {'fixture': fixture.target}, 'pg_bin': fixture.pg_bin, 'target_dataset': base + '/target', 'asset_destination': tmp_path / 'assets', 'minimum_free_bytes': 0}
    with pytest.raises(BackupError, match='ROLE_COLLIDES'):
        restore_backup(config, manifest, target_options=targets)
    with pytest.raises(BackupError, match='ROLE_COLLIDES|CONFIGURED_DEPLOYMENT'):
        restore_backup(SimpleNamespace(sql={}), manifest, target_options={**targets, 'reuse_deployment_roles': True})
    with pytest.raises(BackupError, match='ROLE_COLLIDES'):
        restore_backup(SimpleNamespace(sql={'api_dsn': make_conninfo(fixture.target, user=fixture.reader), 'worker_dsn': worker_dsn}), manifest, target_options={**targets, 'reuse_deployment_roles': True})
    result = restore_backup(config, manifest, target_options={**targets, 'reuse_deployment_roles': True})
    assert result['status'] == 'restored_verified'
    assert sorted(result['roles']['reused_deployment_roles']) == list(names)
    for dsn in (api_dsn, worker_dsn):
        with psycopg.connect(dsn) as connection:
            assert connection.execute('SELECT value FROM lzo_local.fixture_control').fetchone()[0] == 'restored control metadata'
    with psycopg.connect(fixture.target) as connection:
        after = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in connection.execute('SELECT rolname,rolpassword FROM pg_authid WHERE rolname=ANY(%s)', (list(names),))}
        assert before == after
        connection.execute('ALTER ROLE lzo_backup_fixture_api CREATEDB')
    inventory = json.loads(manifest.read_text())['databases']['fixture']['inventory']
    with pytest.raises(BackupError, match='ROLE_COLLIDES'):
        PostgresArchive(fixture.pg_bin).prepare_roles(fixture.target, [inventory], reuse_deployment_roles=set(names))
    with psycopg.connect(fixture.target) as connection:
        connection.execute('ALTER ROLE lzo_backup_fixture_api NOCREATEDB')
    for flag in ('superuser','createdb','createrole','replication','bypassrls'):
        unsafe = copy.deepcopy(inventory)
        next(role for role in unsafe['roles'] if role['name'] == names[0])[flag] = True
        with pytest.raises(BackupError, match='ROLE_COLLIDES'):
            PostgresArchive(fixture.pg_bin).prepare_roles(fixture.target, [unsafe], reuse_deployment_roles=set(names))


@pytest.fixture
def xadmin_fixture(tmp_path):
    if os.environ.get('LZO_LOCAL_BACKUP_XADMIN_TESTS') != '1':
        pytest.skip('cross-admin isolated-cluster fixture is opt-in')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from uuid import uuid4
    from native_targets import NativeTargets
    targets = NativeTargets.from_environment()
    source_admin, target_admin = targets.admin_dsn(), targets.admin_dsn('restore')
    if conninfo_to_dict(source_admin)['user'] != 'postgres' or conninfo_to_dict(target_admin)['user'] != 'lzo_local_admin':
        pytest.fail('cross-admin fixture requires explicit postgres and lzo_local_admin identities')
    targets.verify_cluster('source')
    targets.verify_cluster('restore')
    suffix = uuid4().hex[:10]
    source_name = 'test_backup_xadmin_source_' + suffix
    target_name = 'test_backup_xadmin_target_' + suffix
    reader = 'lzo_backup_xadmin_reader_' + suffix
    class Fixture:
        def __repr__(self):
            return '<isolated-cross-admin-fixture>'
    fixture = Fixture()
    fixture.source = make_conninfo(source_admin, dbname=source_name)
    fixture.target = make_conninfo(target_admin, dbname=target_name)
    fixture.reader = reader
    fixture.evidence = {}
    fixture.pg_bin = targets.pg_bin
    fixture.source_port, fixture.target_port = targets.source_port, targets.restore_port
    created_source = created_target = created_reader = False
    missing_target_roles = set()
    try:
        with targets.connect_admin('source', autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(reader)))
            created_reader = True
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(source_name)))
            created_source = True
        with targets.connect_admin('restore', autocommit=True) as connection:
            for role in ('postgres', reader):
                if connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                    pytest.fail('cross-admin target role already exists; refusing to reuse it')
                missing_target_roles.add(role)
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target_name)))
            created_target = True
        yield fixture
    finally:
        # Unique names created by this invocation only. Never stop a cluster,
        # reassign shared ownership, or alter either cluster's business database.
        with targets.connect_admin('restore', autocommit=True) as connection:
            if created_target:
                connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target_name)))
            for role in sorted(missing_target_roles):
                if connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                    connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
        with targets.connect_admin('source', autocommit=True) as connection:
            if created_source:
                connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(source_name)))
            if created_reader:
                connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(reader)))
        if fixture.evidence:
            with targets.connect_admin('source') as connection:
                source_remaining = connection.execute('SELECT count(*) FROM pg_database WHERE datname=%s', (source_name,)).fetchone()[0]
                source_roles = connection.execute('SELECT count(*) FROM pg_roles WHERE rolname=%s', (reader,)).fetchone()[0]
            with targets.connect_admin('restore') as connection:
                target_remaining = connection.execute('SELECT count(*) FROM pg_database WHERE datname=%s', (target_name,)).fetchone()[0]
                target_roles = connection.execute('SELECT count(*) FROM pg_roles WHERE rolname=ANY(%s)', (sorted(missing_target_roles),)).fetchone()[0]
            fixture.evidence['fixture_cleanup_verified'] = not any((source_remaining, target_remaining, source_roles, target_roles))
            fixture.evidence['remaining_fixture_databases'] = source_remaining + target_remaining
            fixture.evidence['remaining_created_fixture_roles'] = source_roles + target_roles
            assert fixture.evidence['fixture_cleanup_verified'] is True
            (tmp_path / 'backup-xadmin-readback.json').write_text(json.dumps(fixture.evidence, indent=2), encoding='utf-8')


def test_native_cross_admin_postgis_owners_geometry_and_acl(tmp_path, dataset, xadmin_fixture):
    import psycopg
    from psycopg import sql
    from local_server.backup import PostgresArchive, _comparable_inventory
    fixture = xadmin_fixture
    base, _ = dataset
    with psycopg.connect(fixture.source) as connection:
        connection.execute('CREATE EXTENSION postgis')
        connection.execute('CREATE TABLE public.fixture_geometry(id integer PRIMARY KEY, geom geometry(Point,4326))')
        connection.execute('INSERT INTO public.fixture_geometry VALUES (1,ST_SetSRID(ST_MakePoint(114.3,30.4),4326))')
        connection.execute('REVOKE EXECUTE ON FUNCTION public.st_astext(public.geometry) FROM PUBLIC')
        connection.execute(sql.SQL('GRANT EXECUTE ON FUNCTION public.st_astext(public.geometry) TO {}').format(sql.Identifier(fixture.reader)))
        connection.execute('REVOKE SELECT ON TABLE public.spatial_ref_sys FROM PUBLIC')
        connection.execute(sql.SQL('GRANT SELECT ON TABLE public.spatial_ref_sys TO {}').format(sql.Identifier(fixture.reader)))
    asset = tmp_path / 'model.owl'
    asset.write_text('cross-admin synthetic model')
    manifest = create_backup(SimpleNamespace(), tmp_path / 'backup', source_options={'databases': {'fixture': fixture.source}, 'pg_bin': fixture.pg_bin, 'source_dataset': base + '/source', 'assets': {'owl': asset}, 'writers_stopped': True, 'minimum_free_bytes': 0})
    expected = json.loads(manifest.read_text())['databases']['fixture']['inventory']
    try:
        result = restore_backup(SimpleNamespace(), manifest, target_options={'databases': {'fixture': fixture.target}, 'pg_bin': fixture.pg_bin, 'target_dataset': base + '/target', 'asset_destination': tmp_path / 'assets', 'minimum_free_bytes': 0, 'provision_roles': True})
    except BackupError as error:
        if str(error) == 'RESTORE_SQL_FULL_READBACK_MISMATCH':
            actual = PostgresArchive(fixture.pg_bin).inventory('fixture', fixture.target)
            before, after = _comparable_inventory(expected), _comparable_inventory(actual)
            sections = [key for key in before if before[key] != after.get(key)]
            pytest.fail('cross-admin complete inventory mismatch: ' + ','.join(sections), pytrace=False)
        if str(error) == 'RESTORE_EXTENSION_MEMBER_OWNER_FAILED' and isinstance(error.__context__, psycopg.Error):
            cause = error.__context__
            pytest.fail('cross-admin extension ALTER OWNER failed: SQLSTATE=' + str(cause.sqlstate) + '; ' + str(cause.diag.message_primary), pytrace=False)
        raise
    assert result['status'] == 'restored_verified'
    with psycopg.connect(fixture.target) as connection:
        assert connection.execute('SELECT ST_AsEWKT(geom) FROM public.fixture_geometry').fetchone()[0] == 'SRID=4326;POINT(114.3 30.4)'
        assert connection.execute("SELECT pg_get_userbyid(relowner),has_table_privilege(%s,oid,'SELECT'),has_table_privilege('public',oid,'SELECT') FROM pg_class WHERE oid='public.spatial_ref_sys'::regclass", (fixture.reader,)).fetchone() == ('postgres', True, False)
        assert connection.execute("SELECT pg_get_userbyid(proowner),has_function_privilege(%s,oid,'EXECUTE'),has_function_privilege('public',oid,'EXECUTE') FROM pg_proc WHERE oid='public.st_astext(public.geometry)'::regprocedure", (fixture.reader,)).fetchone() == ('postgres', True, False)
        assert connection.execute("SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='postgres'").fetchone() == (False,False,False,False,False,False)
    assert _comparable_inventory(PostgresArchive(fixture.pg_bin).inventory('fixture', fixture.target)) == _comparable_inventory(expected)
    fixture.evidence.update(status='passed', data_nature='synthetic fixture records in isolated native PostgreSQL/PostGIS databases', source_admin='postgres', target_admin='lzo_local_admin', different_admins_verified=True, source_port=fixture.source_port, target_port=fixture.target_port, postgis_version=next(item['version'] for item in expected['extensions'] if item['name'] == 'postgis'), complete_inventory_verified=True, table_count=len(expected['tables']), geometry_verified=True, spatial_ref_sys_owner_acl_verified=True, provider_function_owner_acl_verified=True, safe_nologin_nosuperuser_source_identity_verified=True, shared_database_or_cluster_reassignment=False, primary_business_databases_modified=False)
