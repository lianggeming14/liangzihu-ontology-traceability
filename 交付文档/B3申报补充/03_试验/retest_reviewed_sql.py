"""Time the unmodified frozen build_csv_database.py --apply in three empty clusters."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
from time import perf_counter

import psycopg
from psycopg import sql
from retest_full_csv import execute, EXPECTED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, pg = args.frozen_root.resolve(), args.pg_bin.resolve()
    private = (root / ".runtime" / args.run_name).resolve()
    if not private.is_relative_to(root / ".runtime") or private == root / ".runtime":
        raise ValueError("Use a new private run directory")
    private.mkdir(parents=True, exist_ok=False)
    with args.archive.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == EXPECTED
    checkout = private / "source"
    shutil.copytree(root / "scripts", checkout / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    for relative in ("config/fish-review.example.json", "docs/csv-batch/source-manifest.json",
                     "docs/csv-batch/relation-map.json", "datasets/fish/source-schema.json"):
        dest = checkout / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, dest)
    sys.path.insert(0, str(checkout / "scripts"))
    from prepare_csv_batch import prepare
    staging = checkout / ".runtime/source-imports/csv-2026-11-09/cb9353499b6e"
    staging.mkdir(parents=True)
    shutil.copy2(args.archive, staging / "source.zip")
    assert prepare(staging / "source.zip", staging / "extracted")["csv_status"] == "passed"
    cred = checkout / ".runtime/fish-l1-acceptance/services.env"
    cred.parent.mkdir()
    result = {"started_utc": datetime.now(timezone.utc).isoformat(), "source_commit": "9ded95c99bad3a37a5d82d932db07454e2923c1f",
              "input_zip_sha256": EXPECTED, "command": "python scripts/build_csv_database.py --apply",
              "input_extraction": "prepared before timing; frozen command rechecks every extracted source and ZIP member",
              "includes_rdf": False, "runs": []}
    for number in range(1, 4):
        with socket.socket() as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", 25449))
        run = private / f"new-cluster-{number}"
        run.mkdir()
        data = run / "postgres"
        dbpass, ownerpass = secrets.token_urlsafe(35), secrets.token_urlsafe(35)
        pwfile = run / "init-password"
        pwfile.write_text(dbpass + "\n", encoding="ascii")
        try:
            execute([pg / "initdb.exe", "-D", data, "-U", "b3_admin", "--encoding=UTF8", "--locale=C",
                     "--auth=scram-sha-256", "--pwfile", pwfile])
        finally:
            pwfile.unlink()
        execute([pg / "pg_ctl.exe", "-D", data, "-l", run / "postgres-private.log",
                 "-o", "-h 127.0.0.1 -p 25449", "-w", "start"])
        sample = {"run": number, "status": "failed"}
        try:
            with psycopg.connect(host="127.0.0.1", port=25449, user="b3_admin", password=dbpass,
                                 dbname="postgres", autocommit=True) as admin:
                row = admin.execute("SELECT current_setting('data_directory'), inet_server_port(),version()").fetchone()
                assert Path(row[0]).resolve() == data and row[1] == 25449
                result["postgres_version"] = row[2]
                admin.execute(sql.SQL("CREATE ROLE lzo_gis_owner LOGIN PASSWORD {}").format(sql.Literal(ownerpass)))
                admin.execute("CREATE DATABASE lzo_gis OWNER lzo_gis_owner")
            with psycopg.connect(host="127.0.0.1", port=25449, user="lzo_gis_owner", password=ownerpass,
                                 dbname="lzo_gis") as owner:
                assert owner.execute("SELECT to_regnamespace('csv_batch_a4d78be79a83')").fetchone() == (None,)
            cred.write_text("APP_ENV=test\nLZO_GIS_MIGRATION_DATABASE_URL=postgresql+psycopg://lzo_gis_owner:" +
                            ownerpass + "@127.0.0.1:25449/lzo_gis\n", encoding="ascii")
            before = perf_counter()
            with (run / "command-output.txt").open("wb") as output:
                execution = subprocess.run([sys.executable, "scripts/build_csv_database.py", "--apply"],
                                           cwd=checkout, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
            elapsed = perf_counter() - before
            report = json.loads((checkout / "docs/csv-batch/pg-readback.json").read_text(encoding="utf-8"))
            sample.update(process_wall_seconds=elapsed, command_exit=execution.returncode, readback=report)
            if (execution.returncode == 0 and report["status"] == "passed" and report["schema_created"]
                    and report["transaction_committed"] and report["raw_rows_checked"] == 153862
                    and report["nodes_checked"] == 153862 and report["relations_checked"] == 810934):
                sample["status"] = "passed"
            print(number, sample["status"], round(elapsed, 3), flush=True)
        finally:
            cred.unlink(missing_ok=True)
            execute([pg / "pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop"])
            sample["cluster_stopped"] = True
            result["runs"].append(sample)
            result["updated_utc"] = datetime.now(timezone.utc).isoformat()
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if sample["status"] != "passed":
            raise SystemExit("Frozen --apply did not complete")


if __name__ == "__main__":
    main()
