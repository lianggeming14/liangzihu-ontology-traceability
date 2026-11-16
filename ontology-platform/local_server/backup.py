"""Complete, private, portable logical backup and explicit-new-target restore.

Credentials are supplied in memory and passed to PostgreSQL tools through their
environment, never command arguments, manifests, log messages or public assets.
No operation stops a source service, changes source data or reuses source PIDs.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from .integrity import IntegrityError, _Multiset, rdf_dataset_digest, sha256_file


class BackupError(ValueError):
    pass


_FORMAT = 'local-server-portable-backup-v1'
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$')
_SECRET_NAME = re.compile(r'(^|[._-])(credentials?|passwords?|secrets?|tokens?|private[._-]?key)([._-]|$)', re.I)


def _canonical_host(value):
    value = value.lower().rstrip('.')
    if value in {'localhost', '127.0.0.1', '::1', '[::1]'}:
        return 'loopback'
    try:
        addresses = sorted({r[4][0] for r in socket.getaddrinfo(value, None)})
    except OSError:
        addresses = [value]
    return ','.join(addresses)


def _database_identity(dsn):
    try:
        fields = conninfo_to_dict(str(dsn))
        if not fields.get('dbname'):
            raise ValueError()
        host = fields.get('hostaddr') or fields.get('host', 'localhost')
        if ',' in host or ',' in fields.get('port', '') or fields.get('service'):
            raise ValueError()
        return {'host': _canonical_host(host), 'port': int(fields.get('port', 5432)), 'database': fields['dbname']}
    except Exception:
        raise BackupError('INVALID_DATABASE_CONFIGURATION') from None


def _dataset_identity(url):
    try:
        parts = urlsplit(str(url))
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError()
        decoded = unquote(parts.path)
        if any(piece in {'.', '..'} for piece in decoded.split('/')) or '\\' in decoded or '%' in decoded:
            raise ValueError()
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        return {'scheme': parts.scheme, 'host': _canonical_host(parts.hostname), 'port': port, 'path': decoded.rstrip('/')}
    except Exception:
        raise BackupError('INVALID_DATASET_CONFIGURATION') from None


def _dataset_data(url):
    _dataset_identity(url)
    return str(url).rstrip('/') + '/data'


def _safe_path(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(part in {'', '.', '..'} or ':' in part or '\\' in part for part in relative.parts):
        raise BackupError('BACKUP_PATH_INVALID')
    result = root.joinpath(*relative.parts)
    if not result.resolve().is_relative_to(root.resolve()) or result.is_symlink():
        raise BackupError('BACKUP_PATH_ESCAPE')
    return result


def _check_space(path, options):
    threshold = int(options.get('minimum_free_bytes', 512 * 1024 * 1024))
    parent = Path(path)
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < threshold:
        raise BackupError('INSUFFICIENT_DISK_SPACE')


def _file_record(root, path):
    return {'file': path.relative_to(root).as_posix(), **sha256_file(path)}


def _reject_secret(path):
    if path.name == '.env' or path.suffix.lower() in {'.env', '.pem', '.key', '.p12', '.pfx'} or _SECRET_NAME.search(path.name):
        raise BackupError('SECRET_MUST_BE_STORED_SEPARATELY')


def _asset_plan(assets):
    planned = []
    for label, supplied in sorted(assets.items()):
        if not _NAME.fullmatch(label):
            raise BackupError('INVALID_ASSET_LABEL')
        root = Path(supplied)
        if not root.exists() or root.is_symlink():
            raise BackupError('ASSET_MISSING_OR_SYMLINK')
        _reject_secret(root)
        files = [root] if root.is_file() else sorted(root.rglob('*'))
        for path in files:
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve() if root.is_dir() else root.parent.resolve()):
                raise BackupError('ASSET_PATH_ESCAPE')
            _reject_secret(path)
            if path.is_file():
                relative = path.name if root.is_file() else path.relative_to(root).as_posix()
                planned.append((label, relative, path))
    return planned


def _gzip_asset(source, target):
    digest, size = hashlib.sha256(), 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as incoming, target.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as outgoing:
        for block in iter(lambda: incoming.read(1024 * 1024), b''):
            digest.update(block)
            size += len(block)
            outgoing.write(block)
    return {'raw_sha256': digest.hexdigest(), 'raw_size_bytes': size}


def _download_dataset(url, destination, *, timeout=7200):
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client, client.stream('GET', _dataset_data(url), headers={'Accept': 'application/n-quads'}) as response:
            if response.status_code != 200 or 'application/n-quads' not in response.headers.get('content-type', '').lower():
                raise BackupError('FULL_DATASET_EXPORT_UNAVAILABLE')
            with destination.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as output:
                for block in response.iter_bytes(1024 * 1024):
                    output.write(block)
    except BackupError:
        raise
    except Exception:
        raise BackupError('FULL_DATASET_EXPORT_FAILED') from None


def _assert_dataset_empty(url, *, timeout=60):
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client, client.stream('GET', _dataset_data(url), headers={'Accept': 'application/n-quads'}) as response:
            if response.status_code != 200 or 'application/n-quads' not in response.headers.get('content-type', '').lower():
                raise BackupError('RESTORE_RDF_EMPTY_CHECK_FAILED')
            for line in response.iter_lines():
                if line.strip() and not line.lstrip().startswith('#'):
                    raise BackupError('RESTORE_RDF_TARGET_NOT_EMPTY')
    except BackupError:
        raise
    except Exception:
        raise BackupError('RESTORE_RDF_EMPTY_CHECK_FAILED') from None


def _upload_dataset(url, source, *, timeout=7200):
    def blocks():
        with gzip.open(source, 'rb') as incoming:
            yield from iter(lambda: incoming.read(1024 * 1024), b'')
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = client.post(_dataset_data(url), headers={'Content-Type': 'application/n-quads'}, content=blocks())
            if response.status_code not in {200, 201, 204}:
                raise BackupError('FULL_DATASET_RESTORE_FAILED')
    except BackupError:
        raise
    except Exception:
        raise BackupError('FULL_DATASET_RESTORE_FAILED') from None


class PostgresArchive:
    """pg_dump custom archives plus complete non-system-schema readback."""
    def __init__(self, pg_bin):
        self.pg_bin = Path(pg_bin)
        self.connections = {}

    def _run(self, tool, dsn, arguments):
        fields = conninfo_to_dict(str(dsn))
        env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
        variables = {'dbname': 'PGDATABASE', 'host': 'PGHOST', 'hostaddr': 'PGHOSTADDR', 'port': 'PGPORT', 'user': 'PGUSER', 'password': 'PGPASSWORD', 'connect_timeout': 'PGCONNECT_TIMEOUT', 'application_name': 'PGAPPNAME', 'options': 'PGOPTIONS', 'sslmode': 'PGSSLMODE', 'sslrootcert': 'PGSSLROOTCERT', 'sslcert': 'PGSSLCERT', 'sslkey': 'PGSSLKEY', 'target_session_attrs': 'PGTARGETSESSIONATTRS', 'channel_binding': 'PGCHANNELBINDING', 'gssencmode': 'PGGSSENCMODE'}
        for name, value in fields.items():
            if name not in variables:
                raise BackupError('POSTGRES_TOOL_CONNECTION_OPTION_UNSUPPORTED')
            env[variables[name]] = str(value)
        executable = self.pg_bin / (tool + ('.exe' if os.name == 'nt' else ''))
        try:
            result = subprocess.run([str(executable), *map(str, arguments)], env=env, capture_output=True, check=False)
        except OSError:
            raise BackupError('POSTGRES_TOOL_UNAVAILABLE') from None
        if result.returncode:
            raise BackupError('POSTGRES_' + tool.upper().replace('-', '_') + '_FAILED')

    @staticmethod
    def _schemas(connection):
        return [row[0] for row in connection.execute("SELECT nspname FROM pg_namespace WHERE nspname <> 'information_schema' AND nspname NOT LIKE 'pg\\_%' ESCAPE '\\' ORDER BY nspname")]

    @staticmethod
    def _tables(connection):
        return [(row[0], row[1], row[2]) for row in connection.execute("SELECT n.nspname,c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' AND c.relkind IN ('r','p','m','f') ORDER BY n.nspname,c.relname")]

    @staticmethod
    def _security_inventory(connection):
        namespace = "n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'"
        schemas = [{'schema': n, 'owner': o, 'acl': a} for n, o, a in connection.execute("SELECT n.nspname,pg_get_userbyid(n.nspowner),CASE WHEN n.nspacl IS NULL THEN NULL ELSE ARRAY(SELECT x::text FROM unnest(n.nspacl) x ORDER BY x::text) END FROM pg_namespace n WHERE " + namespace + ' ORDER BY n.nspname')]
        relations = [{'schema': n, 'name': r, 'kind': k, 'owner': o, 'acl': a} for n, r, k, o, a in connection.execute("SELECT n.nspname,c.relname,c.relkind,pg_get_userbyid(c.relowner),CASE WHEN c.relacl IS NULL THEN NULL ELSE ARRAY(SELECT x::text FROM unnest(c.relacl) x ORDER BY x::text) END FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE " + namespace + ' ORDER BY n.nspname,c.relname')]
        routines = [{'schema': n, 'name': r, 'identity_arguments': args, 'kind': k, 'owner': o, 'acl': a, 'security_definer': sd, 'definition': definition} for n, r, args, k, o, a, sd, definition in connection.execute("SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),p.prokind,pg_get_userbyid(p.proowner),CASE WHEN p.proacl IS NULL THEN NULL ELSE ARRAY(SELECT x::text FROM unnest(p.proacl) x ORDER BY x::text) END,p.prosecdef,CASE WHEN p.prokind='a' THEN NULL ELSE pg_get_functiondef(p.oid) END FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE " + namespace + ' ORDER BY n.nspname,p.proname,pg_get_function_identity_arguments(p.oid)')]
        types = [{'schema': n, 'name': r, 'kind': k, 'owner': o, 'acl': a} for n, r, k, o, a in connection.execute("SELECT n.nspname,t.typname,t.typtype,pg_get_userbyid(t.typowner),CASE WHEN t.typacl IS NULL THEN NULL ELSE ARRAY(SELECT x::text FROM unnest(t.typacl) x ORDER BY x::text) END FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE " + namespace + ' ORDER BY n.nspname,t.typname')]
        defaults = [{'schema': n, 'owner': o, 'object_type': kind, 'acl': a} for n, o, kind, a in connection.execute("SELECT n.nspname,pg_get_userbyid(d.defaclrole),d.defaclobjtype,ARRAY(SELECT x::text FROM unnest(d.defaclacl) x ORDER BY x::text) FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace ORDER BY n.nspname NULLS FIRST,pg_get_userbyid(d.defaclrole),d.defaclobjtype")]
        owner, acl = connection.execute("SELECT pg_get_userbyid(datdba),CASE WHEN datacl IS NULL THEN NULL ELSE ARRAY(SELECT x::text FROM unnest(datacl) x ORDER BY x::text) END FROM pg_database WHERE datname=current_database()").fetchone()
        database_acl = [{'grantee': 'PUBLIC' if grantee == 0 else grantee_name, 'grantor': grantor, 'privilege': privilege, 'grantable': grantable} for grantee, grantee_name, grantor, privilege, grantable in connection.execute("SELECT a.grantee,pg_get_userbyid(a.grantee),pg_get_userbyid(a.grantor),a.privilege_type,a.is_grantable FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a WHERE d.datname=current_database() ORDER BY a.grantee::regrole::text,a.grantor::regrole::text,a.privilege_type,a.is_grantable")]
        required = {owner}
        for group in (schemas, relations, routines, types, defaults):
            required.update(item['owner'] for item in group)
        # ACL identities are queried from PostgreSQL, never parsed out of quoted
        # aclitem strings (role names may contain punctuation or whitespace).
        for catalog, owner_column, acl_column, join in [('pg_namespace','nspowner','nspacl',''), ('pg_class','relowner','relacl','JOIN pg_namespace n ON n.oid=o.relnamespace'), ('pg_proc','proowner','proacl','JOIN pg_namespace n ON n.oid=o.pronamespace'), ('pg_type','typowner','typacl','JOIN pg_namespace n ON n.oid=o.typnamespace'), ('pg_default_acl','defaclrole','defaclacl','LEFT JOIN pg_namespace n ON n.oid=o.defaclnamespace')]:
            if catalog == 'pg_namespace':
                query = "SELECT pg_get_userbyid(r.oid) FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a CROSS JOIN LATERAL (VALUES(a.grantee),(a.grantor)) r(oid) WHERE r.oid<>0 AND " + namespace
            else:
                query = f'SELECT pg_get_userbyid(r.oid) FROM {catalog} o {join} CROSS JOIN LATERAL aclexplode(o.{acl_column}) a CROSS JOIN LATERAL (VALUES(a.grantee),(a.grantor)) r(oid) WHERE r.oid<>0 AND ' + ('(n.nspname IS NULL OR (' + namespace + '))' if catalog == 'pg_default_acl' else namespace)
            required.update(row[0] for row in connection.execute(query))
        required.update(row[0] for row in connection.execute("SELECT pg_get_userbyid(r.oid) FROM pg_attribute o JOIN pg_class c ON c.oid=o.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(o.attacl) a CROSS JOIN LATERAL (VALUES(a.grantee),(a.grantor)) r(oid) WHERE r.oid<>0 AND " + namespace))
        required.update(item[key] for item in database_acl for key in ('grantee','grantor') if item[key] != 'PUBLIC')
        membership_columns = {r[0] for r in connection.execute("SELECT attname FROM pg_attribute WHERE attrelid='pg_auth_members'::regclass AND attnum>0 AND NOT attisdropped")}
        options = 'm.inherit_option,m.set_option' if 'inherit_option' in membership_columns else 'NULL::boolean,NULL::boolean'
        all_memberships = [{'role': role, 'member': member, 'grantor': grantor, 'admin_option': admin, 'inherit_option': inherit, 'set_option': setting} for role, member, grantor, admin, inherit, setting in connection.execute('SELECT pg_get_userbyid(m.roleid),pg_get_userbyid(m.member),pg_get_userbyid(m.grantor),m.admin_option,' + options + ' FROM pg_auth_members m ORDER BY pg_get_userbyid(m.roleid),pg_get_userbyid(m.member),pg_get_userbyid(m.grantor)')]
        memberships = []
        while True:
            relevant = [item for item in all_memberships if item['member'] in required]
            expanded = required | {item[key] for item in relevant for key in ('role','grantor')}
            if expanded == required:
                memberships = relevant
                break
            required = expanded
        return {'schema_security': schemas, 'relation_security': relations, 'routine_security': routines, 'type_security': types, 'default_privileges': defaults, 'database_security': {'owner': owner, 'acl': acl, 'acl_privileges': database_acl}, 'required_roles': sorted(required), 'role_memberships': memberships}

    @contextmanager
    def hold_sources(self, databases):
        # SHARE locks wait for existing writers, block new DML, and remain held
        # across SQL/RDF/assets. Every pg_dump joins its exported snapshot.
        with ExitStack() as stack:
            snapshots = {}
            try:
                for name, dsn in sorted(databases.items()):
                    connection = stack.enter_context(psycopg.connect(dsn))
                    self.connections[name] = connection
                    connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
                    connection.execute("SET LOCAL lock_timeout='15s'")
                    for schema, table, kind in self._tables(connection):
                        if kind in {'r', 'p'}:
                            connection.execute(sql.SQL('LOCK TABLE {}.{} IN SHARE MODE').format(sql.Identifier(schema), sql.Identifier(table)))
                        elif kind == 'f':
                            raise BackupError('FOREIGN_TABLE_REQUIRES_EXPLICIT_PORTABLE_CAPTURE')
                    snapshots[name] = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
                yield snapshots
            except BackupError:
                raise
            except Exception:
                raise BackupError('SOURCE_SNAPSHOT_OR_LOCK_FAILED') from None
            finally:
                self.connections.clear()

    def inventory(self, name, dsn):
        owned = name not in self.connections
        connection = psycopg.connect(dsn) if owned else self.connections[name]
        try:
            connection.execute("SET LOCAL TIME ZONE 'UTC'")
            connection.execute("SET LOCAL DateStyle='ISO, YMD'")
            connection.execute('SET LOCAL extra_float_digits=3')
            schemas = self._schemas(connection)
            extensions = [{'name': n, 'version': v, 'schema': s} for n, v, s in connection.execute('SELECT e.extname,e.extversion,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname')]
            roles = [{'name': n, 'login': l, 'superuser': s, 'inherit': i, 'createdb': d, 'createrole': r, 'replication': p, 'bypassrls': b} for n, l, s, i, d, r, p, b in connection.execute("SELECT rolname,rolcanlogin,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname NOT LIKE 'pg\\_%' ESCAPE '\\' ORDER BY rolname")]
            tables = []
            for schema, table, kind in self._tables(connection):
                columns = [{'name': n, 'type': t, 'not_null': nn, 'default': d, 'generated': g, 'identity': i, 'acl': acl} for n, t, nn, d, g, i, acl in connection.execute('SELECT a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid),a.attgenerated,a.attidentity,CASE WHEN a.attacl IS NULL THEN NULL ELSE ARRAY(SELECT x::text FROM unnest(a.attacl) x ORDER BY x::text) END FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum', (schema, table))]
                constraints = [{'name': n, 'definition': d} for n, d in connection.execute('SELECT con.conname,pg_get_constraintdef(con.oid,true) FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s ORDER BY con.conname', (schema, table))]
                accumulator = _Multiset()
                # ONLY prevents partition rows being counted both in parent and
                # child tables. Materialized views are included and read back.
                with connection.cursor(name='backup_rows_' + uuid4().hex) as rows:
                    rows.itersize = 2000
                    rows.execute(sql.SQL('SELECT row_to_json(t)::text FROM ONLY {}.{} t').format(sql.Identifier(schema), sql.Identifier(table)))
                    for (value,) in rows:
                        accumulator.add(value)
                tables.append({'schema': schema, 'name': table, 'kind': kind, 'columns': columns, 'constraints': constraints, 'row_count': accumulator.count, 'row_sha256': accumulator.digest()})
            sequences = [{'schema': s, 'name': n, 'last_value': str(v) if v is not None else None} for s, n, v in connection.execute("SELECT schemaname,sequencename,last_value FROM pg_sequences WHERE schemaname <> 'information_schema' AND schemaname NOT LIKE 'pg\\_%' ESCAPE '\\' ORDER BY schemaname,sequencename")]
            return {'schemas': schemas, 'extensions': extensions, 'roles': roles, 'tables': tables, 'sequences': sequences, 'server_version': connection.info.server_version, **self._security_inventory(connection)}
        except BackupError:
            raise
        except Exception:
            raise BackupError('POSTGRES_FULL_READBACK_FAILED') from None
        finally:
            if owned:
                connection.close()

    def capture(self, name, dsn, path, snapshot):
        inventory = self.inventory(name, dsn)
        self._run('pg_dump', dsn, ['--format=custom', '--compress=6', '--snapshot=' + snapshot, '--file=' + str(path)])
        return inventory

    def assert_empty(self, name, dsn):
        try:
            with psycopg.connect(dsn) as connection:
                # New PostGIS databases may have the extension's own public
                # relations. User schemas/data and other non-extension objects
                # are always rejected; nothing is dropped by this tool.
                count = connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e') AND c.relkind IN ('r','p','v','m','S','f')").fetchone()[0]
                routines = connection.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')").fetchone()[0]
                types = connection.execute("SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' AND t.typelem=0 AND (t.typtype <> 'c' OR EXISTS (SELECT 1 FROM pg_class c WHERE c.oid=t.typrelid AND c.relkind='c')) AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e')").fetchone()[0]
                schemas = [s for s in self._schemas(connection) if s != 'public' and not connection.execute('SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE n.nspname=%s', (s,)).fetchone()]
                if count or routines or types or schemas:
                    raise BackupError('RESTORE_SQL_TARGET_NOT_EMPTY')
        except BackupError:
            raise
        except Exception:
            raise BackupError('RESTORE_SQL_EMPTY_CHECK_FAILED') from None

    def prepare_roles(self, dsn, inventories, *, provision=False, reuse_deployment_roles=()):
        required = sorted({role for inventory in inventories for role in inventory.get('required_roles', [])})
        role_details = {role['name']: role for inventory in inventories for role in inventory.get('roles', [])}
        memberships = {tuple(sorted(item.items())): item for inventory in inventories for item in inventory.get('role_memberships', [])}
        created = []
        reused = []
        reusable = set(reuse_deployment_roles)
        try:
            with psycopg.connect(dsn) as connection:
                admin = connection.execute('SELECT current_user').fetchone()[0]
                for role in required:
                    existing = connection.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
                    if existing:
                        documented = role_details.get(role, {})
                        safe_binding = (role in reusable and role != admin and existing[0] is True and not any(existing[1:6]) and documented.get('login') is True and all(documented.get(flag) is False for flag in ('superuser','createdb','createrole','replication','bypassrls')) and documented.get('inherit') == existing[6])
                        if role != admin and any(existing[:6]) and not safe_binding:
                            raise BackupError('RESTORE_SOURCE_ROLE_COLLIDES_WITH_PRIVILEGED_OR_LOGIN_TARGET')
                        if role != admin and role in role_details and existing[6] != role_details[role].get('inherit', True):
                            raise BackupError('RESTORE_SOURCE_ROLE_INHERIT_MISMATCH')
                        if safe_binding:
                            reused.append(role)
                        continue
                    if not provision or role.startswith('pg_'):
                        raise BackupError('RESTORE_SOURCE_ROLE_MISSING')
                    inherit = 'INHERIT' if role_details.get(role, {}).get('inherit', True) else 'NOINHERIT'
                    connection.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS ' + inherit).format(sql.Identifier(role)))
                    created.append(role)
                for membership in memberships.values():
                    expected = (membership['admin_option'], membership.get('inherit_option'), membership.get('set_option'))
                    options = 'm.admin_option,m.inherit_option,m.set_option' if connection.info.server_version >= 160000 else 'm.admin_option,NULL::boolean,NULL::boolean'
                    existing = connection.execute('SELECT ' + options + ' FROM pg_auth_members m WHERE pg_get_userbyid(m.roleid)=%s AND pg_get_userbyid(m.member)=%s AND pg_get_userbyid(m.grantor)=%s', (membership['role'], membership['member'], membership['grantor'])).fetchone()
                    if existing == expected:
                        continue
                    if not provision:
                        raise BackupError('RESTORE_SOURCE_ROLE_MEMBERSHIP_MISSING_OR_DIFFERENT')
                    if connection.info.server_version >= 160000:
                        command = sql.SQL('GRANT {} TO {} WITH ADMIN {}, INHERIT {}, SET {} GRANTED BY {}').format(sql.Identifier(membership['role']), sql.Identifier(membership['member']), sql.SQL('TRUE' if expected[0] else 'FALSE'), sql.SQL('TRUE' if expected[1] else 'FALSE'), sql.SQL('TRUE' if expected[2] else 'FALSE'), sql.Identifier(membership['grantor']))
                    else:
                        if membership['grantor'] != admin:
                            raise BackupError('RESTORE_ROLE_GRANTOR_UNSUPPORTED_ON_TARGET_VERSION')
                        command = sql.SQL('GRANT {} TO {}' + (' WITH ADMIN OPTION' if expected[0] else '')).format(sql.Identifier(membership['role']), sql.Identifier(membership['member']))
                    connection.execute(command)
            return {'created': created, 'required': required, 'reused_deployment_roles': reused, 'policy': 'new source identities are NOLOGIN/NOSUPERUSER; explicit safe Config API/worker LOGIN bindings retain target passwords and attributes'}
        except BackupError:
            raise
        except Exception:
            raise BackupError('RESTORE_SAFE_SOURCE_ROLE_PROVISION_FAILED') from None

    @staticmethod
    def _restore_database_security(dsn, inventory):
        security = inventory.get('database_security')
        if not security:
            return
        try:
            with psycopg.connect(dsn) as connection:
                database = connection.execute('SELECT current_database()').fetchone()[0]
                connection.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(sql.Identifier(database), sql.Identifier(security['owner'])))
                if security['acl'] is None:
                    return
                grantees = [row[0] for row in connection.execute("SELECT DISTINCT CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a WHERE d.datname=current_database()")]
                for grantee in sorted(set(grantees + ['PUBLIC'])):
                    if grantee == security['owner']:
                        continue
                    connection.execute(sql.SQL('REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}').format(sql.Identifier(database), sql.SQL('PUBLIC') if grantee == 'PUBLIC' else sql.Identifier(grantee)))
                for entry in security['acl_privileges']:
                    if entry['privilege'] not in {'CREATE', 'CONNECT', 'TEMPORARY', 'TEMP'}:
                        raise BackupError('RESTORE_DATABASE_PRIVILEGE_UNSUPPORTED')
                    connection.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(entry['grantor'])))
                    grantee = sql.SQL('PUBLIC') if entry['grantee'] == 'PUBLIC' else sql.Identifier(entry['grantee'])
                    connection.execute(sql.SQL('GRANT ' + entry['privilege'] + ' ON DATABASE {} TO {}' + (' WITH GRANT OPTION' if entry['grantable'] else '')).format(sql.Identifier(database), grantee))
                    connection.execute('RESET ROLE')
        except BackupError:
            raise
        except Exception:
            raise BackupError('RESTORE_DATABASE_OWNER_OR_ACL_FAILED') from None

    @staticmethod
    def _restore_extension_member_owners(dsn, inventory):
        """Restore provider-object owners omitted by pg_dump extension DDL.

        CREATE EXTENSION runs as the new cluster admin. pg_dump intentionally
        omits individual extension-member definitions/ALTER OWNER statements,
        so pg_restore alone changes their owners across differently named
        admins. Only target extension members with an exact source inventory
        identity are eligible here; ordinary objects, roles and other databases
        are never reassigned. ALTER OWNER also preserves/translates ACL grantors.
        Complete owner/ACL/definition/data readback still follows this step.
        """
        extension_versions = {item['name']: (item['version'], item['schema']) for item in inventory.get('extensions', [])}
        relation_owners = {(item['schema'], item['name'], item['kind']): item['owner'] for item in inventory.get('relation_security', [])}
        routine_owners = {(item['schema'], item['name'], item['identity_arguments'], item['kind']): item['owner'] for item in inventory.get('routine_security', [])}
        type_owners = {(item['schema'], item['name'], item['kind']): item['owner'] for item in inventory.get('type_security', [])}
        namespace = "n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'"
        try:
            with psycopg.connect(dsn) as connection:
                membership = "JOIN pg_depend d ON d.classid='{catalog}'::regclass AND d.objid=o.oid AND d.objsubid=0 AND d.refclassid='pg_extension'::regclass AND d.deptype='e' JOIN pg_extension e ON e.oid=d.refobjid JOIN pg_namespace en ON en.oid=e.extnamespace "
                def expected_owner(mapping, identity, extension, version, schema):
                    if extension_versions.get(extension) != (version, schema) or identity not in mapping:
                        raise BackupError('RESTORE_EXTENSION_MEMBER_SOURCE_IDENTITY_MISMATCH')
                    return mapping[identity]
                relations = connection.execute('SELECT n.nspname,o.relname,o.relkind,pg_get_userbyid(o.relowner),e.extname,e.extversion,en.nspname FROM pg_class o JOIN pg_namespace n ON n.oid=o.relnamespace ' + membership.format(catalog='pg_class') + 'WHERE ' + namespace + " ORDER BY CASE WHEN o.relkind='S' THEN 1 ELSE 0 END,n.nspname,o.relname").fetchall()
                relation_commands = {'r': 'TABLE', 'p': 'TABLE', 'f': 'FOREIGN TABLE', 'v': 'VIEW', 'm': 'MATERIALIZED VIEW', 'S': 'SEQUENCE'}
                for schema, name, kind, owner, extension, version, extension_schema in relations:
                    expected = expected_owner(relation_owners, (schema, name, kind), extension, version, extension_schema)
                    if kind == 'S':
                        # An OWNED BY sequence follows its table's owner. Read
                        # again after tables rather than using the initial row.
                        owner = connection.execute('SELECT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s', (schema, name)).fetchone()[0]
                    if expected != owner and kind in relation_commands:
                        connection.execute(sql.SQL('ALTER ' + relation_commands[kind] + ' {}.{} OWNER TO {}').format(sql.Identifier(schema), sql.Identifier(name), sql.Identifier(expected)))
                    # Index/toast/composite relation owners follow their table
                    # or type owner automatically, and are checked at readback.
                # Companion array types cannot be ALTERed directly; PostgreSQL
                # changes them with their element type. They remain in the full
                # type-security readback, so no owner mismatch is exempted.
                types = connection.execute('SELECT n.nspname,o.typname,o.typtype,pg_get_userbyid(o.typowner),e.extname,e.extversion,en.nspname FROM pg_type o JOIN pg_namespace n ON n.oid=o.typnamespace ' + membership.format(catalog='pg_type') + 'WHERE ' + namespace + ' AND NOT EXISTS (SELECT 1 FROM pg_type element WHERE element.typarray=o.oid) ORDER BY n.nspname,o.typname').fetchall()
                for schema, name, kind, owner, extension, version, extension_schema in types:
                    expected = expected_owner(type_owners, (schema, name, kind), extension, version, extension_schema)
                    if expected != owner:
                        connection.execute(sql.SQL('ALTER ' + ('DOMAIN' if kind == 'd' else 'TYPE') + ' {}.{} OWNER TO {}').format(sql.Identifier(schema), sql.Identifier(name), sql.Identifier(expected)))
                routines = connection.execute('SELECT n.nspname,o.proname,pg_get_function_identity_arguments(o.oid),o.prokind,pg_get_userbyid(o.proowner),e.extname,e.extversion,en.nspname FROM pg_proc o JOIN pg_namespace n ON n.oid=o.pronamespace ' + membership.format(catalog='pg_proc') + 'WHERE ' + namespace + ' ORDER BY n.nspname,o.proname,pg_get_function_identity_arguments(o.oid)').fetchall()
                for schema, name, arguments, kind, owner, extension, version, extension_schema in routines:
                    expected = expected_owner(routine_owners, (schema, name, arguments, kind), extension, version, extension_schema)
                    if expected != owner:
                        command = 'PROCEDURE' if kind == 'p' else ('AGGREGATE' if kind == 'a' else 'FUNCTION')
                        arguments = '*' if kind == 'a' and not arguments else arguments
                        connection.execute(sql.SQL('ALTER ' + command + ' {}.{}({}) OWNER TO {}').format(sql.Identifier(schema), sql.Identifier(name), sql.SQL(arguments), sql.Identifier(expected)))
        except BackupError:
            raise
        except Exception:
            raise BackupError('RESTORE_EXTENSION_MEMBER_OWNER_FAILED') from None

    def restore(self, name, dsn, path, *, inventory=None):
        self._run('pg_restore', dsn, ['--exit-on-error', '--single-transaction', '--dbname=' + conninfo_to_dict(str(dsn))['dbname'], str(path)])
        if inventory:
            self._restore_extension_member_owners(dsn, inventory)
            self._restore_database_security(dsn, inventory)


def create_backup(config, destination, *, source_options=None):
    options = dict(source_options or {})
    if options.get('writers_stopped') is not True:
        raise BackupError('SOURCE_WRITERS_MUST_BE_STOPPED_AND_CONFIRMED')
    databases = options.get('databases')
    if not isinstance(databases, dict) or not databases or not options.get('source_dataset') or 'pg_bin' not in options:
        raise BackupError('EXPLICIT_COMPLETE_SOURCE_CONFIGURATION_REQUIRED')
    if any(not _NAME.fullmatch(name) for name in databases):
        raise BackupError('INVALID_DATABASE_LABEL')
    identities = {name: _database_identity(dsn) for name, dsn in databases.items()}
    rdf_identity = _dataset_identity(options['source_dataset'])
    assets = _asset_plan(options.get('assets', {}))
    root = Path(destination).resolve()
    for supplied in options.get('assets', {}).values():
        asset_root = Path(supplied).resolve()
        if root.is_relative_to(asset_root) or asset_root.is_relative_to(root):
            raise BackupError('BACKUP_DESTINATION_ASSET_OVERLAP')
    if root.exists() and any(root.iterdir()):
        raise BackupError('BACKUP_DESTINATION_NOT_EMPTY')
    _check_space(root, options)
    root.mkdir(parents=True, exist_ok=True)
    backend = options.get('_postgres') or PostgresArchive(options['pg_bin'])
    manifest = {'format': _FORMAT, 'backup_id': str(uuid4()), 'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'capturing', 'source': {'databases': identities, 'dataset': rdf_identity}, 'consistency': {'local_writers_stopped': True, 'sql': 'all-table-share-locks-and-exported-snapshots', 'rdf': 'whole-dataset-single-response; source RDF writers stopped by operator'}, 'databases': {}, 'assets': [], 'software': {'python': os.sys.version.split()[0]}, 'credentials': 'excluded; retain source/target configuration and authorization keys separately'}
    try:
        with backend.hold_sources(databases) as snapshots:
            for name, dsn in sorted(databases.items()):
                _check_space(root, options)
                archive = root / ('sql/' + name + '.pgdump')
                archive.parent.mkdir(parents=True, exist_ok=True)
                inventory = backend.capture(name, dsn, archive, snapshots[name])
                manifest['databases'][name] = {**_file_record(root, archive), 'inventory': inventory, 'archive_format': 'postgresql-custom-compressed', 'ownership_policy': 'preserve source object owners and ACL; provision missing role names only as safe NOLOGIN identities with explicit opt-in'}
            _check_space(root, options)
            rdf = root / 'rdf/dataset.nq.gz'
            rdf.parent.mkdir(parents=True, exist_ok=True)
            _download_dataset(options['source_dataset'], rdf, timeout=options.get('http_timeout', 7200))
            manifest['rdf'] = {**_file_record(root, rdf), 'inventory': rdf_dataset_digest(rdf, work_dir=root), 'format': 'application/n-quads+gzip', 'scope': 'entire-dataset-default-and-all-named-graphs'}
            for label, relative, source in assets:
                _check_space(root, options)
                target = _safe_path(root, 'assets/' + label + '/' + relative + '.gz')
                raw = _gzip_asset(source, target)
                manifest['assets'].append({**_file_record(root, target), **raw, 'label': label, 'relative_path': relative, 'compression': 'gzip'})
        manifest['status'] = 'complete'
        path = root / 'manifest.json'
        path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        (root / 'manifest.sha256').write_text(sha256_file(path)['sha256'] + '\n', encoding='ascii')
        return path
    except Exception as error:
        (root / 'FAILED.json').write_text(json.dumps({'status': 'failed', 'code': str(error) if isinstance(error, (BackupError, IntegrityError)) else 'BACKUP_FAILED', 'backup_id': manifest['backup_id']}), encoding='utf-8')
        if isinstance(error, (BackupError, IntegrityError)):
            raise
        raise BackupError('BACKUP_FAILED') from None


def _load_manifest(manifest):
    if isinstance(manifest, dict):
        manifest = manifest.get('manifest_path')
    if not manifest:
        raise BackupError('MANIFEST_PATH_REQUIRED')
    path = Path(manifest).resolve()
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        raise BackupError('MANIFEST_MISSING_OR_INVALID') from None
    if saved.get('format') != _FORMAT or saved.get('status') != 'complete' or not saved.get('databases') or not saved.get('rdf'):
        raise BackupError('MANIFEST_INCOMPLETE_OR_UNSUPPORTED')
    return path, saved


def verify_backup(manifest):
    path, saved = _load_manifest(manifest)
    root = path.parent
    records = list(saved['databases'].values()) + [saved['rdf']] + saved.get('assets', [])
    # Validate paths first so that even a modified manifest cannot traverse out.
    for record in records:
        _safe_path(root, record['file'])
    try:
        expected = (root / 'manifest.sha256').read_text(encoding='ascii').strip()
        if sha256_file(path)['sha256'] != expected:
            raise BackupError('MANIFEST_HASH_MISMATCH')
        for record in records:
            file_path = _safe_path(root, record['file'])
            actual = sha256_file(file_path)
            if actual['size_bytes'] != record['size_bytes'] or actual['sha256'] != record['sha256']:
                raise BackupError('BACKUP_FILE_HASH_OR_SIZE_MISMATCH')
        actual = rdf_dataset_digest(_safe_path(root, saved['rdf']['file']), work_dir=root)
        if actual != saved['rdf']['inventory']:
            raise BackupError('BACKUP_RDF_INTEGRITY_MISMATCH')
        for asset in saved.get('assets', []):
            digest, size = hashlib.sha256(), 0
            with gzip.open(_safe_path(root, asset['file']), 'rb') as incoming:
                for block in iter(lambda: incoming.read(1024 * 1024), b''):
                    size += len(block)
                    digest.update(block)
            if size != asset['raw_size_bytes'] or digest.hexdigest() != asset['raw_sha256']:
                raise BackupError('BACKUP_ASSET_INTEGRITY_MISMATCH')
    except (OSError, EOFError, IntegrityError):
        raise BackupError('BACKUP_MISSING_OR_INVALID_INTEGRITY') from None
    return {'status': 'verified', 'manifest_path': str(path), 'backup_id': saved['backup_id'], 'database_count': len(saved['databases']), 'asset_count': len(saved.get('assets', [])), 'rdf': saved['rdf']['inventory']}


def _constraint_tokens(definition):
    """Lex SQL without inspecting quoted values/identifiers or comments."""
    tokens, position, length = [], 0, len(definition)
    while position < length:
        char = definition[position]
        if char.isspace():
            position += 1
            continue
        start = position
        escape = char in 'Ee' and position + 1 < length and definition[position + 1] == "'"
        unicode_quote = definition[position:position + 2].lower() == 'u&' and position + 2 < length and definition[position + 2] in "'\""
        if char in "'\"" or escape or unicode_quote:
            position += 1 if escape else (2 if unicode_quote else 0)
            quote = definition[position]
            position += 1
            while position < length:
                if escape and definition[position] == '\\':
                    position += 2
                elif definition[position] == quote:
                    if position + 1 < length and definition[position + 1] == quote:
                        position += 2
                    else:
                        position += 1
                        break
                else:
                    position += 1
            else:
                return None
            kind = 'literal' if char == "'" else ('identifier' if char == '"' else 'opaque')
            tokens.append((kind, definition[start:position]))
        elif definition.startswith('--', position):
            end = definition.find('\n', position + 2)
            position = length if end < 0 else end
            tokens.append(('opaque', definition[start:position]))
        elif definition.startswith('/*', position):
            depth, position = 1, position + 2
            while position < length and depth:
                if definition.startswith('/*', position):
                    depth, position = depth + 1, position + 2
                elif definition.startswith('*/', position):
                    depth, position = depth - 1, position + 2
                else:
                    position += 1
            if depth:
                return None
            tokens.append(('opaque', definition[start:position]))
        elif char == '$' and (delimiter := re.match(r'\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$', definition[position:])):
            marker = delimiter.group()
            end = definition.find(marker, position + len(marker))
            if end < 0:
                return None
            position = end + len(marker)
            tokens.append(('opaque', definition[start:position]))
        elif char.isalpha() or char == '_' or ord(char) >= 128:
            position += 1
            while position < length and (definition[position].isalnum() or definition[position] in '_$' or ord(definition[position]) >= 128):
                position += 1
            tokens.append(('word', definition[start:position]))
        elif definition.startswith('::', position):
            tokens.append(('symbol', '::'))
            position += 2
        elif char in '+-*/<>=~!@#%^&|':
            position += 1
            while position < length and definition[position] in '+-*/<>=~!@#%^&|' and not definition.startswith(('--','/*'), position):
                position += 1
            tokens.append(('symbol', definition[start:position]))
        else:
            # Punctuation stays separate from maximal SQL operator tokens.
            tokens.append(('symbol', char))
            position += 1
    return tokens


def _canonical_check_definition(definition):
    """Compare one proven pg_dump deparse rewrite, retaining original text.

    For CHECK only, ARRAY['x'::character varying, ...]::text[] and
    ARRAY['x'::character varying::text, ...] express the same built-in cast.
    No arbitrary casts, identifiers, literal values, functions, typmods, schema
    types or expressions are removed or interpreted. Quoted tokens stay opaque.
    """
    tokens = _constraint_tokens(definition)
    if not tokens or tokens[0][0] != 'word' or tokens[0][1].upper() != 'CHECK':
        return definition
    output, position = [], 0
    def word(token, value):
        return token[0] == 'word' and token[1].lower() == value
    while position < len(tokens):
        if word(tokens[position], 'array') and position + 1 < len(tokens) and tokens[position + 1] == ('symbol', '['):
            end = position + 2
            elements, current = [], []
            while end < len(tokens) and tokens[end] != ('symbol', ']'):
                if tokens[end] == ('symbol', ','):
                    elements.append(current)
                    current = []
                else:
                    current.append(tokens[end])
                end += 1
            elements.append(current)
            literal_varchar = all(len(element) == 4 and element[0][0] == 'literal' and element[1] == ('symbol', '::') and word(element[2], 'character') and word(element[3], 'varying') for element in elements)
            tail = tokens[end + 1:end + 5]
            outer_text_array = len(tail) == 4 and tail[0] == ('symbol', '::') and word(tail[1], 'text') and tail[2:] == [('symbol', '['), ('symbol', ']')]
            if end < len(tokens) and literal_varchar and outer_text_array:
                output.extend(tokens[position:position + 2])
                for index, element in enumerate(elements):
                    if index:
                        output.append(('symbol', ','))
                    output.extend(element + [('symbol', '::'), ('word', 'text')])
                output.append(('symbol', ']'))
                position = end + 5
                continue
        output.append(tokens[position])
        position += 1
    return tuple(output)


def _comparable_inventory(inventory):
    # Source password/login/superuser flags are documented but never replicated.
    # Object owners, ACL, SECURITY DEFINER and necessary memberships are compared.
    comparable = deepcopy({key: value for key, value in inventory.items() if key not in {'roles', 'server_version'}})
    for table in comparable.get('tables', []):
        for constraint in table.get('constraints', []):
            if isinstance(constraint.get('definition'), str):
                constraint['definition'] = _canonical_check_definition(constraint['definition'])
    return comparable


def restore_backup(config, manifest, *, target_options=None):
    options = dict(target_options or {})
    path, saved = _load_manifest(manifest)
    databases = options.get('databases')
    if not isinstance(databases, dict) or set(databases) != set(saved['databases']) or not options.get('target_dataset') or 'pg_bin' not in options:
        raise BackupError('EXPLICIT_NEW_COMPLETE_TARGET_CONFIGURATION_REQUIRED')
    deployment_roles = set()
    if options.get('reuse_deployment_roles') is True:
        configured = getattr(config, 'sql', {})
        targets = [_database_identity(dsn) for dsn in databases.values()]
        for key in ('api_dsn', 'worker_dsn'):
            dsn = configured.get(key)
            try:
                user = conninfo_to_dict(dsn).get('user') if isinstance(dsn, str) else None
                valid = user and _database_identity(dsn) in targets
            except Exception:
                valid = False
            if not valid:
                raise BackupError('RESTORE_CONFIGURED_DEPLOYMENT_ROLE_BINDING_REQUIRED')
            deployment_roles.add(user)
    source_identities = list(saved['source']['databases'].values())
    for dsn in databases.values():
        if _database_identity(dsn) in source_identities:
            raise BackupError('RESTORE_SAME_SOURCE_SQL_REFUSED')
    if _dataset_identity(options['target_dataset']) == saved['source']['dataset']:
        raise BackupError('RESTORE_SAME_SOURCE_RDF_REFUSED')
    if 'asset_destination' not in options:
        raise BackupError('EXPLICIT_NEW_ASSET_DESTINATION_REQUIRED')
    destination = Path(options['asset_destination']).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise BackupError('RESTORE_ASSET_TARGET_NOT_EMPTY')
    if destination.is_relative_to(path.parent) or path.parent.is_relative_to(destination):
        raise BackupError('RESTORE_ASSET_TARGET_OVERLAPS_BACKUP')
    verify_backup(path)
    _check_space(destination, options)
    backend = options.get('_postgres') or PostgresArchive(options['pg_bin'])
    # All targets are checked before the first mutation. A failed restore is
    # retained for inspection and never declared active or cleaned destructively.
    resumed = {}
    resume = options.get('resume_verified_targets') is True
    for name, dsn in sorted(databases.items()):
        try:
            backend.assert_empty(name, dsn)
        except BackupError as error:
            if not resume or str(error) != 'RESTORE_SQL_TARGET_NOT_EMPTY':
                raise
            actual = backend.inventory(name, dsn)
            if _comparable_inventory(actual) != _comparable_inventory(saved['databases'][name]['inventory']):
                raise BackupError('RESTORE_SQL_RESUME_FULL_READBACK_MISMATCH') from None
            resumed[name] = actual
    resumed_rdf = None
    try:
        _assert_dataset_empty(options['target_dataset'])
    except BackupError as error:
        if not resume or str(error) != 'RESTORE_RDF_TARGET_NOT_EMPTY':
            raise
        with tempfile.TemporaryDirectory(prefix='resume-rdf-readback-', dir=path.parent) as scratch:
            readback = Path(scratch) / 'dataset.nq.gz'
            _download_dataset(options['target_dataset'], readback, timeout=options.get('http_timeout', 7200))
            resumed_rdf = rdf_dataset_digest(readback, work_dir=scratch)
        if resumed_rdf != saved['rdf']['inventory']:
            raise BackupError('RESTORE_RDF_RESUME_FULL_READBACK_MISMATCH') from None
    report = {'status': 'restoring', 'backup_id': saved['backup_id'], 'deployment_id': str(uuid4()), 'databases': {}, 'asset_count': 0, 'resumed_verified_databases': sorted(resumed)}
    try:
        role_options = {'provision': options.get('provision_roles') is True}
        if deployment_roles:
            role_options['reuse_deployment_roles'] = deployment_roles
        report['roles'] = backend.prepare_roles(next(iter(databases.values())), [item['inventory'] for item in saved['databases'].values()], **role_options)
        for name, dsn in sorted(databases.items()):
            _check_space(destination, options)
            if name in resumed:
                actual = resumed[name]
            else:
                backend.restore(name, dsn, _safe_path(path.parent, saved['databases'][name]['file']), inventory=saved['databases'][name]['inventory'])
                actual = backend.inventory(name, dsn)
            if _comparable_inventory(actual) != _comparable_inventory(saved['databases'][name]['inventory']):
                raise BackupError('RESTORE_SQL_FULL_READBACK_MISMATCH')
            report['databases'][name] = {'status': 'full_readback_verified', 'table_count': len(actual['tables']), 'schemas': actual['schemas'], 'restore_action': 'resumed_verified' if name in resumed else 'pg_restore'}
        actual = resumed_rdf
        if actual is None:
            _upload_dataset(options['target_dataset'], _safe_path(path.parent, saved['rdf']['file']), timeout=options.get('http_timeout', 7200))
            with tempfile.TemporaryDirectory(prefix='restore-readback-', dir=path.parent) as scratch:
                readback = Path(scratch) / 'dataset.nq.gz'
                _download_dataset(options['target_dataset'], readback, timeout=options.get('http_timeout', 7200))
                actual = rdf_dataset_digest(readback, work_dir=scratch)
        if actual != saved['rdf']['inventory']:
            raise BackupError('RESTORE_RDF_FULL_READBACK_MISMATCH')
        report['rdf_restore_action'] = 'resumed_verified' if resumed_rdf is not None else 'uploaded_and_readback_verified'
        destination.mkdir(parents=True, exist_ok=True)
        for asset in saved.get('assets', []):
            target = _safe_path(destination, asset['label'] + '/' + asset['relative_path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(_safe_path(path.parent, asset['file']), 'rb') as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            record = sha256_file(target)
            if record['sha256'] != asset['raw_sha256'] or record['size_bytes'] != asset['raw_size_bytes']:
                raise BackupError('RESTORE_ASSET_READBACK_MISMATCH')
            report['asset_count'] += 1
        report.update(status='restored_verified', rdf=actual, ownership_policy='source object owner/ACL/SECURITY DEFINER and necessary role memberships preserved; new missing roles NOLOGIN/NOSUPERUSER; no source credentials or PID cache copied')
        (destination / 'restore-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report
    except Exception as error:
        report.update(status='failed', code=str(error) if isinstance(error, (BackupError, IntegrityError)) else 'RESTORE_FAILED')
        # Failure evidence stays beside the backup, not inside an untrusted path.
        (path.parent / ('restore-failed-' + report['deployment_id'] + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if isinstance(error, (BackupError, IntegrityError)):
            raise
        raise BackupError('RESTORE_FAILED') from None


def _placement_no_links(path):
    """Reject symlinks/junctions on every component before resolving a path."""
    cursor=Path(path).absolute()
    while True:
        if cursor.is_symlink() or (hasattr(cursor,'is_junction') and cursor.is_junction()):
            raise BackupError('ASSET_PLACEMENT_LINK_REFUSED')
        if cursor == cursor.parent:
            break
        cursor=cursor.parent


def _placement_business_path(value):
    if not isinstance(value,str) or not value or any(part in ('','.','..') for part in value.split('/')):
        raise BackupError('ASSET_PLACEMENT_PATH_INVALID')
    forbidden={'deployment.json','ownership.json','postmaster.pid','postmaster.opts','pg_version','tdb.lock',
               'process.json','processes.json','start.lock','stop-request.json','graceful-stop.request'}
    for part in value.split('/'):
        _reject_secret(Path(part))
        if part.startswith('.') or part.lower() in forbidden or part.lower().endswith('.pid') or '\\' in part or ':' in part or '\x00' in part:
            raise BackupError('ASSET_PLACEMENT_PRIVATE_OR_PATH_REFUSED')
    return value


def place_restored_assets(config, manifest, *, target_options=None):
    """Copy only hash-verified business assets out of a verified restore stage.

    SQL/RDF restoration stays separate and the staging tree is retained. The
    CLI requires HTTP/worker stopped. A pending marker blocks ordinary start
    until every declared asset is aligned and verified; this function never
    starts a process, edits deployment ownership or publishes a release.
    """
    from .config import contained_path
    from .lifecycle import atomic_json
    options=dict(target_options or {})
    path,saved=_load_manifest(manifest)
    expected=(path.parent/'manifest.sha256').read_text(encoding='ascii').strip()
    if sha256_file(path)['sha256'] != expected:
        raise BackupError('MANIFEST_HASH_MISMATCH')
    if not options.get('asset_destination'):
        raise BackupError('ASSET_PLACEMENT_STAGE_REQUIRED')
    stage=Path(options['asset_destination']).absolute()
    _placement_no_links(stage)
    stage=stage.resolve()
    report_path=stage/'restore-report.json'
    _placement_no_links(report_path)
    try:
        restore=json.loads(report_path.read_text(encoding='utf-8'))
        good=(restore.get('status')=='restored_verified' and restore.get('backup_id')==saved['backup_id']
              and restore.get('rdf')==saved['rdf']['inventory']
              and set(restore.get('databases',{}))==set(saved['databases'])
              and restore.get('asset_count')==len(saved.get('assets',[])))
        for name,database in saved['databases'].items():
            proof=restore.get('databases',{}).get(name,{})
            good=good and proof.get('status')=='full_readback_verified' and proof.get('table_count')==len(database['inventory']['tables']) and proof.get('schemas')==database['inventory']['schemas']
        if not good:
            raise BackupError('VERIFIED_COMPLETE_RESTORE_REPORT_REQUIRED')
    except (OSError,ValueError,KeyError,TypeError):
        raise BackupError('VERIFIED_COMPLETE_RESTORE_REPORT_REQUIRED') from None
    pending=contained_path(config.data_dir,'asset-placement.pending.json')
    atomic_json(pending,{'status':'asset_placement_pending','backup_id':saved['backup_id']})
    completed=[]
    try:
        assets=saved.get('assets',[])
        labels={record['label'] for record in assets}
        placement=options.get('asset_placement')
        if not isinstance(placement,dict) or set(placement)!=labels:
            raise BackupError('EXPLICIT_COMPLETE_ASSET_PLACEMENT_REQUIRED')
        bases={'data':config.data_dir,'root':config.root,'review':config.review_dir}
        protected=[config.data_dir/'postgres',config.data_dir/'fuseki',config.runtime_dir,
                   config.data_dir/'deployment.json',pending]
        if getattr(config,'config_path',None):
            protected.append(config.config_path)
        for key in ('pg_data_dir','fuseki_state_dir'):
            if config.runtime.get(key):
                protected.append(contained_path(config.data_dir,config.runtime[key]))
        targets={}
        for label in sorted(labels):
            if not _NAME.fullmatch(label):
                raise BackupError('ASSET_PLACEMENT_LABEL_INVALID')
            _placement_business_path(label)
            spec=placement[label]
            if not isinstance(spec,dict) or set(spec)!={'base','path'} or spec['base'] not in bases:
                raise BackupError('ASSET_PLACEMENT_TARGET_INVALID')
            relative=_placement_business_path(spec['path'])
            if label in ('uploads','imports','releases','cad-imports') and (spec['base']!='data' or relative!=label):
                raise BackupError('BUSINESS_REFERENCE_ROOT_MUST_RETAIN_ITS_LABEL')
            target=_safe_path(Path(bases[spec['base']]),relative)
            _placement_no_links(target)
            target=target.resolve()
            if target.is_relative_to(stage) or stage.is_relative_to(target):
                raise BackupError('ASSET_PLACEMENT_STAGE_OVERLAP')
            if any(target==Path(value).resolve() or target.is_relative_to(Path(value).resolve()) or Path(value).resolve().is_relative_to(target) for value in protected):
                raise BackupError('ASSET_PLACEMENT_NATIVE_OR_PRIVATE_TARGET_REFUSED')
            if any(target==other or target.is_relative_to(other) or other.is_relative_to(target) for other in targets.values()):
                raise BackupError('ASSET_PLACEMENT_TARGETS_OVERLAP')
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise BackupError('ASSET_PLACEMENT_TARGET_NOT_EMPTY_CONFLICT')
            targets[label]=target
        plan=[]
        names=set()
        for record in assets:
            relative=_placement_business_path(record['relative_path'])
            key=record['label']+'/'+relative
            if key.casefold() in names:
                raise BackupError('ASSET_PLACEMENT_DUPLICATE_PATH')
            names.add(key.casefold())
            source=_safe_path(stage,key)
            _placement_no_links(source)
            if not source.is_file():
                raise BackupError('RESTORED_ASSET_MISSING')
            actual=sha256_file(source)
            if actual['sha256']!=record['raw_sha256'] or actual['size_bytes']!=record['raw_size_bytes']:
                raise BackupError('RESTORED_ASSET_HASH_OR_SIZE_MISMATCH')
            plan.append((record,source,relative))
        volumes={}
        for record,_,_ in plan:
            parent=targets[record['label']].parent
            while not parent.exists():parent=parent.parent
            key=parent.stat().st_dev
            volumes.setdefault(key,[parent,0])[1]+=record['raw_size_bytes']
        for parent,required in volumes.values():
            if shutil.disk_usage(parent).free-required < int(options.get('minimum_free_bytes',512*1024*1024)):
                raise BackupError('INSUFFICIENT_DISK_SPACE')
        work={}
        for label,target in targets.items():
            target.parent.mkdir(parents=True,exist_ok=True)
            _placement_no_links(target.parent)
            work[label]=target.parent/('asset-placement-work-'+str(uuid4()))
            work[label].mkdir()
        for record,source,relative in plan:
            target=_safe_path(work[record['label']],relative)
            target.parent.mkdir(parents=True,exist_ok=True)
            with source.open('rb') as incoming,target.open('xb') as outgoing:
                shutil.copyfileobj(incoming,outgoing,1024*1024)
            actual=sha256_file(target)
            if actual['sha256']!=record['raw_sha256'] or actual['size_bytes']!=record['raw_size_bytes']:
                raise BackupError('ASSET_PLACEMENT_COPY_READBACK_MISMATCH')
        for label,target in targets.items():
            _placement_no_links(target)
            if target.exists():
                if not target.is_dir() or any(target.iterdir()):
                    raise BackupError('ASSET_PLACEMENT_TARGET_NOT_EMPTY_CONFLICT')
                target.rmdir()  # Only a checked empty directory; never recursive.
            target.parent.mkdir(parents=True,exist_ok=True)
            work[label].rename(target)
            completed.append(label)
        result={'status':'assets_placed_verified','backup_id':saved['backup_id'],'restore_deployment_id':restore.get('deployment_id'),
                'asset_count':len(plan),'labels':{label:placement[label] for label in completed},'staging_retained':True,
                'native_ownership':'unchanged','services_started':False,'release_published':False}
        atomic_json(config.runtime_dir/'asset-placement-report.json',result)
        pending.unlink()
        return result
    except Exception as error:
        code=str(error) if isinstance(error,BackupError) else 'ASSET_PLACEMENT_FAILED'
        try:atomic_json(config.runtime_dir/'asset-placement-report.json',{'status':'failed','backup_id':saved['backup_id'],'code':code,'completed_labels':completed,'services_started':False,'release_published':False})
        except OSError:pass
        if isinstance(error,BackupError):
            raise
        raise BackupError('ASSET_PLACEMENT_FAILED') from None
