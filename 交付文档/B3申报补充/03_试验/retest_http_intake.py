"""Replay the reviewed ZIP and its byte-preserving CSV projection via frozen HTTP."""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import threading
from time import perf_counter
from unittest.mock import patch
import os
from zipfile import ZipFile

from dotenv import dotenv_values
import httpx


def attempt(config, store, worker, client, archive, variant, index):
    from local_server.worker import process_job

    data = archive.read_bytes()
    report = {"run": index, "variant": variant, "bytes": len(data),
              "sha256": hashlib.sha256(data).hexdigest(), "free_before_bytes": shutil.disk_usage(config.data_dir).free}
    before = perf_counter()
    response = client.post("/api/v1/batches", params={"filename": "source.zip"}, content=data,
                           headers={"Authorization": "Bearer " + config.write_token, "Content-Type": "application/zip"})
    accepted = perf_counter()
    report.update(http_status=response.status_code, http_response_seconds=accepted - before)
    response.raise_for_status()
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    owner = f"intake-fixture-{index}"
    job = worker.claim_job(owner)
    assert job and job["job_id"] == job_id
    try:
        process_job(config, worker, job, owner)
    except ValueError as error:
        messages = {"Full snapshot archive may contain only CSV files",
                    "Source date-time requires YYYY-MM-DDTHH:MM:SS with an XSD timezone"}
        report["worker_reason"] = str(error) if str(error) in messages else type(error).__name__
    ended = perf_counter()
    terminal = store.get_job(job_id)
    report.update(job_id=job_id, terminal_status=terminal["status"], public_error=terminal.get("error"),
                  active_release_count=len(store.list_releases()), submit_to_terminal_seconds=ended - before)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, programs = args.frozen_root.resolve(), args.tools.resolve()
    private = (root / ".runtime" / args.run_name).resolve()
    if not private.is_relative_to(root / ".runtime") or private == root / ".runtime":
        raise ValueError("Use a fresh private run directory")
    private.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(root))
    from local_server.config import Config
    from local_server.http import make_handler
    from local_server.lifecycle import NativeServices
    from local_server.provision import provision_fresh
    from local_server.store import Store

    original = args.archive.resolve()
    with original.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == "a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524"
    slim = private / "csv-only.zip"
    with ZipFile(original) as source, ZipFile(slim, "w") as target:
        members = [m for m in source.infolist() if m.filename.startswith("csv/") and m.filename.endswith(".csv")]
        assert len(members) == 66
        for member in members:
            target.writestr(member, source.read(member))
    output = {"started_utc": datetime.now(timezone.utc).isoformat(),
              "source_commit": "9ded95c99bad3a37a5d82d932db07454e2923c1f", "samples": [], "cleanup": []}
    for index in (1, 2, 3):
        target = private / ("instance-" + str(index))
        provision_fresh(root, target, programs / "postgresql-17.11/bin", programs / "java-21",
                        programs / "fuseki-6.2.0", pg_port=26671, fuseki_port=24271, http_port=8917)
        with patch.dict(os.environ, dotenv_values(target / "private.env", interpolate=False)):
            config = Config.load(target / "config.json")
        assert config.data_dir == target and config.host == "127.0.0.1" and config.port == 8917
        native = NativeServices(config)
        try:
            native.start()
            admin = Store(config, "admin")
            with admin.connect() as conn:
                row = conn.execute("SELECT current_setting('data_directory') AS path,inet_server_port() AS port").fetchone()
                assert Path(row["path"]).resolve() == target / "postgres/data" and row["port"] == 26671
            admin.ensure_schema()
            api, worker = Store(config), Store(config, role="worker")
            assert not api.list_jobs() and not api.list_releases()
            with ThreadingHTTPServer((config.host, config.port), make_handler(config, api)) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with httpx.Client(base_url="http://127.0.0.1:8917", trust_env=False, timeout=60) as client:
                        for variant, archive in [("original_pinned_zip", original), ("business_csv_only", slim)]:
                            sample = attempt(config, api, worker, client, archive, variant, index)
                            output["samples"].append(sample)
                            print(index, variant, sample["terminal_status"], sample.get("worker_reason", ""), flush=True)
                finally:
                    server.shutdown()
                    thread.join()
        finally:
            native.stop()
            output["cleanup"].append(native.status())
            args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
