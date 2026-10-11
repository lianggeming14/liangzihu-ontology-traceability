"""Isolated backends. SQLite proves behavior only; PostgreSQL is a separate gate."""
from pathlib import Path
import os
import re
import sys
import uuid
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path):
    backend = request.param
    schema = "test_ontology_" + uuid.uuid4().hex
    if backend == "postgresql":
        dsn = os.environ.get("TEST_DATABASE_URL")
        if not dsn:
            pytest.skip("PostgreSQL gate UNVERIFIED: TEST_DATABASE_URL is not configured")
        if not dsn.startswith(("postgresql://", "postgres://")):
            pytest.fail("TEST_DATABASE_URL must explicitly name a dedicated PostgreSQL test database")
        from agri.db import Database
        db = Database(dsn, schema=schema)
    else:
        from agri.sqlite_db import SQLiteDatabase
        db = SQLiteDatabase("sqlite:///" + str(tmp_path / "isolated-test.db"))
    db.migrate()
    # Re-running migrations is part of startup/recovery behavior.
    db.migrate()
    yield db
    if backend == "postgresql":
        assert re.fullmatch(r"test_ontology_[0-9a-f]{32}", schema)
        with db.transaction() as tx:
            tx.execute('DROP SCHEMA "' + schema + '" CASCADE')


@pytest.fixture()
def service(database):
    from agri.service import Service
    return Service(database)
