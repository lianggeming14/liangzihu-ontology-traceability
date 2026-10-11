"""Consistent SQLite development backups. Uses sqlite3.Connection.backup().

All backup and restored files are confined to implementation/data/backups.
Restore creates a NEW file; this script never overwrites a running database.
This verifies SQLite persistence only, not PostgreSQL recovery or RPO/RTO.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "data" / "backups"
sys.path.insert(0, str(ROOT))
from agri.sqlite_db import _decimal_check


def confined(path, parent):
    resolved = path.resolve()
    allowed = parent.resolve()
    if ROOT not in allowed.parents or allowed == ROOT:
        raise ValueError("Backup directory must be inside the implementation workspace")
    if allowed not in resolved.parents:
        raise ValueError("Path must be inside " + str(allowed))
    return resolved


def output_path(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:db|sqlite)", name):
        raise ValueError("Use a plain .db or .sqlite backup filename")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    path = confined(BACKUPS / name, BACKUPS)
    if path.exists():
        raise ValueError("Existing backup will not be overwritten")
    return path


def connection(path, readonly=False):
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) if readonly else sqlite3.connect(str(path))
    conn.create_function("decimal_nonnegative", 1,
                         lambda value: _decimal_check(value, "nonnegative"), deterministic=True)
    conn.create_function("decimal_positive", 1,
                         lambda value: _decimal_check(value, "positive"), deterministic=True)
    conn.create_function("decimal_lte", 2,
                         lambda value, other: _decimal_check(value, "lte", other), deterministic=True)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def inspect(path):
    conn = connection(path, readonly=True)
    try:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != ["ok"] or foreign_keys:
            raise RuntimeError("Backup integrity/foreign-key verification failed")
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = conn.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
        return {"integrity_check": "ok", "foreign_key_violations": 0, "table_counts": counts}
    finally:
        conn.close()


def copy_database(source, destination):
    source = source.resolve(strict=True)
    if ROOT not in source.parents or source == destination:
        raise ValueError("Source must be a different existing database inside the workspace")
    staging = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".pending")
    source_conn = destination_conn = None
    try:
        source_conn = connection(source, readonly=True)
        destination_conn = connection(staging)
        # This API produces a transactionally consistent backup including WAL data.
        source_conn.backup(destination_conn, pages=256, sleep=0.01)
        destination_conn.close()
        destination_conn = None
        source_conn.close()
        source_conn = None
        verification = inspect(staging)
        # Windows rename fails if the destination already exists; do not replace.
        staging.rename(destination)
        manifest = {
            "backend": "sqlite-development",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source.relative_to(ROOT)),
            "backup": str(destination.relative_to(ROOT)),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "consistent_backup_api": True,
            "postgresql_validation": False,
            **verification,
        }
        destination.with_suffix(destination.suffix + ".json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
    finally:
        if destination_conn is not None:
            destination_conn.close()
        if source_conn is not None:
            source_conn.close()
        if staging.exists():
            staging.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--source", type=Path, default=ROOT / "data" / "agri.db")
    backup.add_argument("--name", default="agri-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".db")
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--name", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        source = args.source if args.source.is_absolute() else ROOT / args.source
        result = copy_database(source, output_path(args.name))
    elif args.command == "restore":
        source = args.backup if args.backup.is_absolute() else ROOT / args.backup
        source = confined(source, BACKUPS)
        result = copy_database(source, output_path(args.name))
        result["restored_to_new_file"] = True
    else:
        source = args.file if args.file.is_absolute() else ROOT / args.file
        result = inspect(confined(source, BACKUPS))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
