"""PostgreSQL connection boundary; psycopg is imported only on use.

Development backends must implement transaction()/execute() and clearly identify
that PostgreSQL validation has not run. No in-memory fallback occurs here.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import re


class Database:
    backend = 'postgresql'

    def __init__(self, dsn, schema='agri'):
        if not isinstance(dsn, str) or not dsn:
            raise ValueError('A PostgreSQL DSN is required')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,62}', schema):
            raise ValueError('Invalid PostgreSQL schema name')
        self.dsn = dsn
        self.schema = schema

    @contextmanager
    def transaction(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg import sql
        except ImportError as exc:
            raise RuntimeError('PostgreSQL driver missing: install psycopg[binary]. No fallback was used.') from exc
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(self.schema)))
            yield conn

    def migrate(self):
        import psycopg
        from psycopg import sql
        folder = Path(__file__).resolve().parents[1] / 'migrations'
        migrations = [p for p in sorted(folder.glob('[0-9][0-9][0-9]_*.sql')) if not p.name.endswith('.sqlite.sql')]
        applied, versions = [], set()
        with psycopg.connect(self.dsn) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('agri-migration:' + self.schema,))
            conn.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(self.schema)))
            conn.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(self.schema)))
            conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())')
            for migration in migrations:
                version = migration.name.split('_',1)[0]
                if version in versions: raise RuntimeError('Duplicate migration version: ' + version)
                versions.add(version)
                content = migration.read_text(encoding='utf-8')
                digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
                previous = conn.execute('SELECT checksum FROM schema_migrations WHERE version=%s', (version,)).fetchone()
                if previous:
                    if previous[0] != digest:
                        raise RuntimeError('Migration ' + version + ' checksum changed; use a new migration rather than rewriting history')
                    continue
                conn.execute(content, prepare=False)
                conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES (%s,%s)', (version,digest))
                applied.append(version)
        return {'backend':self.backend, 'schema':self.schema, 'migration':max(versions), 'applied':bool(applied), 'applied_versions':applied}
