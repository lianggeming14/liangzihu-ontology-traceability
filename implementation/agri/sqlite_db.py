"""Persistent SQLite development adapter, explicitly NOT PostgreSQL validation.

BEGIN IMMEDIATE serializes all writers, replacing service FOR UPDATE locks.
This adapter does not claim PostgreSQL concurrency/isolation equivalence.
Monetary/quantity decimals remain strings; all arithmetic belongs in the
service's Decimal operations. It has no fallback into an in-memory database.
"""
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import UUID


def _parameter(value):
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)
    return value


def _translate(statement):
    # Service statements are controlled SQL, never arbitrary client SQL.
    # Advisory locking is already stronger at database level (BEGIN IMMEDIATE).
    if re.match(r'\s*SELECT\s+pg_advisory_xact_lock\s*\(', statement, re.I):
        return 'SELECT 1 AS locked', True
    statement = re.sub(r'\s+FOR\s+UPDATE(?:\s+SKIP\s+LOCKED)?\s*;?\s*$',
                       '', statement, flags=re.I)
    statement = re.sub(r'::(?:jsonb|json|uuid|timestamptz|timestamp|text)\b',
                       '', statement, flags=re.I)
    statement = re.sub(r'\bnow\s*\(\s*\)', "strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                       statement, flags=re.I)
    return statement.replace('%s', '?'), False


class SQLiteSession:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, params=(), **_):
        translated, drop_params = _translate(statement)
        values = () if drop_params else tuple(_parameter(v) for v in (params or ()))
        return self.connection.execute(translated, values)

    def executemany(self, statement, seq):
        translated, drop_params = _translate(statement)
        if drop_params:
            return self.connection.execute(translated)
        return self.connection.executemany(translated, [
            tuple(_parameter(v) for v in values) for values in seq
        ])


def _decimal_check(value, operation, other=None):
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return 0
        if operation == 'nonnegative':
            return int(number >= 0)
        if operation == 'positive':
            return int(number > 0)
        bound = Decimal(str(other))
        return int(bound.is_finite() and number <= bound)
    except Exception:
        return 0


def _dict_row(cursor, row):
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


def _statements(script):
    """Split at complete SQL statements, preserving semicolons inside triggers."""
    buffer = ''
    for char in script:
        buffer += char
        if char == ';' and sqlite3.complete_statement(buffer):
            if buffer.strip():
                yield buffer
            buffer = ''
    if buffer.strip():
        if not sqlite3.complete_statement(buffer + ';'):
            raise ValueError('Incomplete SQLite migration statement')
        yield buffer


class SQLiteDatabase:
    backend = 'sqlite-development'
    schema = 'main'

    def __init__(self, dsn):
        prefix = 'sqlite:///'
        if not isinstance(dsn, str) or not dsn.startswith(prefix):
            raise ValueError('SQLite development DSN must start with sqlite:///')
        name = dsn[len(prefix):]
        if name in ('', ':memory:') or name.startswith('file:'):
            raise ValueError('A persistent absolute SQLite file path is required')
        path = Path(name)
        if not path.is_absolute():
            raise ValueError('SQLite development file path must be absolute')
        self.path = path.resolve()
        self.dsn = dsn
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.row_factory = _dict_row
        conn.create_function('decimal_nonnegative', 1,
                             lambda value: _decimal_check(value, 'nonnegative'), deterministic=True)
        conn.create_function('decimal_positive', 1,
                             lambda value: _decimal_check(value, 'positive'), deterministic=True)
        conn.create_function('decimal_lte', 2,
                             lambda value, other: _decimal_check(value, 'lte', other), deterministic=True)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield SQLiteSession(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self):
        migration = Path(__file__).resolve().parents[1] / 'migrations' / '001_core.sqlite.sql'
        content = migration.read_text(encoding='utf-8')
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        conn = self._connect()
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            old = conn.execute('SELECT checksum FROM schema_migrations WHERE version=?',
                               ('001',)).fetchone()
            if old:
                if old['checksum'] != digest:
                    raise RuntimeError('SQLite migration 001 checksum changed; create a new migration')
                conn.commit()
                return {'backend': self.backend, 'schema': self.schema, 'migration': '001', 'applied': False}
            for statement in _statements(content):
                conn.execute(statement)
            conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES (?,?)',
                         ('001', digest))
            conn.commit()
            return {'backend': self.backend, 'schema': self.schema, 'migration': '001', 'applied': True}
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
