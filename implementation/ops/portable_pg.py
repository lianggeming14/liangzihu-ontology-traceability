"""Manage only a dedicated workspace PostgreSQL instance.

Obtain the Windows x64 ZIP via https://www.postgresql.org/download/windows/
and its official EDB binary link. No installed service is accessed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
BIN_ROOT = RUNTIME / "postgresql"
DATA = RUNTIME / "pg-data"
SECRET = RUNTIME / "pg-local-password.txt"
STATUS = RUNTIME / "postgresql-status.json"
PORT = 55439
USER = DATABASE = "agri_dev"

def run(args, env=None):
    subprocess.run(args, cwd=ROOT, env=env, check=True)

def executable(name):
    matches = list(BIN_ROOT.glob(f"**/bin/{name}.exe"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name}.exe below {BIN_ROOT}; found {len(matches)}")
    return str(matches[0])

def credentials():
    if not SECRET.is_file():
        raise RuntimeError("Dedicated instance not initialized; run install first")
    password = SECRET.read_text(encoding="utf-8").strip()
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    return password, env

def install(archive, expected_sha=None):
    archive = archive.resolve(strict=True)
    if ROOT not in archive.parents:
        raise ValueError("Archive must be inside this implementation workspace")
    if DATA.exists() or BIN_ROOT.exists():
        raise RuntimeError("Existing runtime will not be replaced; inspect it manually")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if expected_sha and digest.lower() != expected_sha.lower():
        raise ValueError("Archive SHA-256 mismatch")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    BIN_ROOT.mkdir()
    with zipfile.ZipFile(archive) as zf:
        for item in zf.infolist():
            target = (BIN_ROOT / item.filename).resolve()
            if BIN_ROOT.resolve() not in target.parents and target != BIN_ROOT.resolve():
                raise ValueError("Archive path escapes dedicated runtime")
            if ((item.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Archive symlinks are not supported")
        zf.extractall(BIN_ROOT)
    password = secrets.token_urlsafe(32)
    SECRET.write_text(password + "\n", encoding="utf-8")
    run([executable("initdb"), "-D", str(DATA), "-U", USER,
         "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C",
         "--pwfile", str(SECRET)])
    STATUS.write_text(json.dumps({
        "state": "initialized_not_started", "host": "127.0.0.1",
        "port": PORT, "user": USER, "database": DATABASE,
        "archive_sha256": digest,
        "archive_digest_independently_verified": bool(expected_sha),
        "version_query_verified": False, "rollback_verified": False,
        "data_directory": str(DATA), "credential_file": str(SECRET),
    }, indent=2), encoding="utf-8")

def start():
    if not (DATA / "PG_VERSION").is_file():
        raise RuntimeError("No dedicated initialized cluster; refusing to start")
    _, env = credentials()
    run([executable("pg_ctl"), "-D", str(DATA), "-l", str(RUNTIME / "postgresql.log"),
         "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "start"], env)
    # Probe our newly started cluster only; never connect to port 5432.
    exists = subprocess.check_output([
        executable("psql"), "-h", "127.0.0.1", "-p", str(PORT), "-U", USER,
        "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{DATABASE}'",
    ], cwd=ROOT, env=env, text=True).strip()
    if exists != "1":
        run([executable("createdb"), "-h", "127.0.0.1", "-p", str(PORT),
             "-U", USER, DATABASE], env)
    print(f"Dedicated PostgreSQL started on 127.0.0.1:{PORT}; run verify next.")

def verify():
    sys.path.insert(0, str(ROOT / ".deps"))
    import psycopg
    password, _ = credentials()
    with psycopg.connect(host="127.0.0.1", port=PORT, user=USER,
                         password=password, dbname=DATABASE, connect_timeout=5) as conn:
        version = conn.execute("SELECT version()").fetchone()[0]
        data_dir = conn.execute("SHOW data_directory").fetchone()[0]
        if Path(data_dir).resolve() != DATA.resolve():
            raise RuntimeError("Unexpected cluster directory; refusing verification")
        conn.execute("CREATE TEMP TABLE rollback_probe (id integer)")
        conn.commit()
        conn.execute("INSERT INTO rollback_probe VALUES (1)")
        conn.rollback()
        count = conn.execute("SELECT COUNT(*) FROM rollback_probe").fetchone()[0]
        if count != 0:
            raise AssertionError("Rollback verification failed")
    state = json.loads(STATUS.read_text(encoding="utf-8"))
    state.update(state="verified_running", version=version,
                 version_query_verified=True, rollback_verified=True,
                 psycopg_version=psycopg.__version__)
    STATUS.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps({"version": version, "rollback_verified": True,
                      "host": "127.0.0.1", "port": PORT, "database": DATABASE}, indent=2))

def stop():
    if not (DATA / "PG_VERSION").is_file():
        raise RuntimeError("No dedicated cluster found; refusing stop")
    run([executable("pg_ctl"), "-D", str(DATA), "-m", "fast", "-w", "stop"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    installer = sub.add_parser("install")
    installer.add_argument("--archive", type=Path, required=True)
    installer.add_argument("--sha256")
    for command in ("start", "verify", "stop"):
        sub.add_parser(command)
    options = parser.parse_args()
    if options.command == "install":
        install(options.archive, options.sha256)
    else:
        globals()[options.command]()
