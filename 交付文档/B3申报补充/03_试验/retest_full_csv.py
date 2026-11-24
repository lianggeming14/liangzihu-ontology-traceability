"""Reproduce the frozen Store tests and full 66-table SQL source intake.

Run with the project Python environment, the 9ded95c9 source tree and the
reviewed source ZIP. The only database used is a newly initialized local
cluster. The SQL intake retains source strings and compares all cells in source
order. It measures source intake, independently of the ontology publisher.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from time import perf_counter

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


HOST = "127.0.0.2"
PORT = 25459  # Exact port required by the old test file. The address is separate.
EXPECTED = "a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524"


def execute(command, **options):
    return subprocess.run(command, stdin=subprocess.DEVNULL, check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                          **options)


def receive_batch(connection, archive, destination, sequence):
    from prepare_csv_batch import prepare

    started = perf_counter()
    manifest = prepare(archive, destination)
    if manifest["archive_sha256"] != EXPECTED or manifest["csv_status"] != "passed":
        raise ValueError("Reviewed CSV identity or integrity mismatch")
    preflight_end = perf_counter()
    files = [item for item in manifest["members"] if item["is_csv"]]
    fields = sum(len(item["header"]) for item in files)
    assert (len(files), manifest["row_count"], fields) == (66, 153862, 1397)
    schema = "source_run_" + str(sequence)
    rows_checked, cells_checked = 0, 0
    with connection.transaction():
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for item in files:
            path = destination / item["path"]
            columns = [sql.Identifier(col) for col in item["header"]]
            names = sql.SQL(", ").join(columns)
            table = sql.Identifier(schema, path.stem)
            types = sql.SQL(", ").join(sql.SQL("{} text NOT NULL").format(col) for col in columns)
            connection.execute(sql.SQL("CREATE TABLE {} (row_number_ bigint GENERATED ALWAYS AS IDENTITY, {})").format(table, types))
            copy_sql = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER, FORCE_NOT_NULL ({}))").format(table, names, names)
            with path.open("rb") as source, connection.cursor().copy(copy_sql) as target:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(block)
    committed = perf_counter()
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        for item in files:
            path = destination / item["path"]
            table = sql.Identifier(schema, path.stem)
            names = sql.SQL(", ").join(sql.Identifier(col) for col in item["header"])
            with connection.cursor(name="verify_source_rows") as cursor, path.open(encoding="utf-8-sig", newline="") as stream:
                cursor.execute(sql.SQL("SELECT {} FROM {} ORDER BY row_number_").format(names, table))
                source = csv.reader(stream, strict=True)
                assert next(source) == item["header"]
                count = 0
                for original, stored in zip(source, cursor, strict=True):
                    assert tuple(original) == stored
                    count += 1
                assert count == item["row_count"]
                rows_checked += count
                cells_checked += count * len(item["header"])
    ended = perf_counter()
    return {"run": sequence, "status": "passed", "archive_sha256": EXPECTED,
            "csvs": len(files), "headers": fields, "source_records_compared": rows_checked,
            "source_cells_compared": cells_checked, "bad_rows": manifest["bad_rows"],
            "preparation_seconds": preflight_end - started, "sql_insert_commit_seconds": committed - preflight_end,
            "committed_readback_seconds": ended - committed, "start_to_verified_seconds": ended - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--private-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, pg, run = args.frozen_root.resolve(), args.pg_bin.resolve(), args.private_run.resolve()
    if not run.is_relative_to(root / ".runtime") or run == root / ".runtime":
        raise ValueError("Use a new private run under the frozen source .runtime")
    run.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(root / "scripts"))
    with socket.socket() as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind((HOST, PORT))
    db = run / "postgres"
    pw = secrets.token_urlsafe(32)
    secret_path = run / "init-password"
    secret_path.write_text(pw + "\n", encoding="ascii")
    try:
        execute([pg / "initdb.exe", "-D", db, "-U", "fixture_admin", "--encoding=UTF8", "--locale=C",
                 "--auth=scram-sha-256", "--pwfile", secret_path])
    finally:
        secret_path.unlink()
    execute([pg / "pg_ctl.exe", "-D", db, "-l", run / "postgres-private.log",
             "-o", f"-h {HOST} -p {PORT}", "-w", "start"])
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "runs": [],
              "basis": "9ded95c99bad3a37a5d82d932db07454e2923c1f",
              "engine": "source verification from frozen prepare_csv_batch.prepare; PostgreSQL COPY of source strings; all cells read back",
              "rdf_or_navigation_published": False}
    try:
        base = dict(host=HOST, port=PORT, user="fixture_admin", password=pw, connect_timeout=5)
        with psycopg.connect(**base, dbname="postgres", autocommit=True) as admin:
            row = admin.execute("SELECT current_setting('data_directory'), inet_server_addr()::text, inet_server_port(), version()").fetchone()
            assert Path(row[0]).resolve() == db and row[1].split("/")[0] == HOST and row[2] == PORT
            report["postgres_version"] = row[3]
            roles = {"admin": ("fixture_admin", pw)}
            for role in ("api", "worker"):
                name, password = "fixture_" + role, secrets.token_urlsafe(32)
                admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))
                roles[role] = (name, password)
            admin.execute("CREATE DATABASE lzo_local_test")
            admin.execute("CREATE DATABASE full_csv_source")
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        for role, (name, password) in roles.items():
            env["LZO_LOCAL_TEST_" + role.upper() + "_DATABASE_URL"] = make_conninfo(
                host=HOST, port=PORT, dbname="lzo_local_test", user=name, password=password)
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", "--tb=short",
                                 "-p", "no:cacheprovider", "--basetemp", str(run / "store-tests"),
                                 "--junitxml", str(run / "store-junit.xml"), "tests/local_server/test_store.py"],
                                cwd=root, env=env, capture_output=True)
        (run / "store-stdout.txt").write_bytes(result.stdout)
        (run / "store-stderr.txt").write_bytes(result.stderr)
        report["store_pytest_exit"] = result.returncode
        with psycopg.connect(**base, dbname="full_csv_source", autocommit=True) as conn:
            for index in range(1, 4):
                sample = receive_batch(conn, args.archive, run / ("private-source-" + str(index)), index)
                report["runs"].append(sample)
                print(json.dumps(sample), flush=True)
    finally:
        execute([pg / "pg_ctl.exe", "-D", db, "-m", "fast", "-w", "stop"])
        report["cluster_stopped"] = True
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["store_pytest_exit"] != 0:
        raise SystemExit(report["store_pytest_exit"])


if __name__ == "__main__":
    main()
