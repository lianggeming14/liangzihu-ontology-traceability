"""Preview or apply Liangzihu records through authenticated backend APIs.

Default commands never write the database. --apply is required for mutations.
Keep real exports and receipts under implementation/runtime/source-imports/
(Git-ignored). Other runtime directories are not automatically ignored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from integrations.liangzihu import (DIRECTORY, MAX_REQUEST_BYTES, canonical_bytes, digest, load_bundle, load_profile,
                                    make_batch, plan_batches, read_records, strict_json)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("API redirect refused; configure the final trusted base URL explicitly")


class ApiClient:
    def __init__(self, base_url, token, *, timeout=120):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use a trusted http(s) base URL without credentials, query or fragment")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Non-loopback API connections require HTTPS")
        if not token or "\n" in token or "\r" in token:
            raise ValueError("Set AGRI_API_TOKEN to an authorized API token; do not put the token in a command or source file")
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout
        self.opener = build_opener(NoRedirects())

    def request(self, path, payload=None, *, key=None):
        body = canonical_bytes(payload) if payload is not None else None
        if body is not None and len(body) > MAX_REQUEST_BYTES:
            raise ValueError("Request exceeds 2 MiB; reduce record size or install definitions separately")
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        request = Request(self.base_url + path, data=body, headers=headers, method="POST" if body is not None else "GET")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
        except HTTPError as exc:
            # Error bodies can contain record values. Return only bounded error metadata.
            try:
                value = strict_json(exc.read(64 * 1024).decode("utf-8"))
                error = value.get("error", {})
                code = error.get("code", "http_error") if isinstance(error, dict) else "http_error"
            except (ValueError, UnicodeError):
                code = "http_error"
            raise ValueError(f"Backend HTTP {exc.code}: {code}; inspect the protected backend receipt/log, not public Git output") from None
        except URLError:
            raise ValueError("Cannot connect to the configured backend; no successful write is confirmed") from None
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("API response exceeds the protected response budget")
        value = strict_json(raw.decode("utf-8"))
        return value.get("data", value)

    def bindings(self, source_id):
        items, offset = [], 0
        while True:
            page = self.request("/api/v1/integration/bindings?" + urlencode({"source_id": source_id, "projection": "identity", "limit": 100, "offset": offset}))
            rows = page.get("items", [])
            if not isinstance(rows, list):
                raise ValueError("Unexpected source bindings response")
            items.extend(rows)
            if len(items) > 100000:
                raise ValueError("Binding snapshot exceeds planner budget; export a bounded source scope")
            if not page.get("has_more"):
                break
            if not rows:
                raise ValueError("Invalid empty paginated bindings response")
            offset = page.get("next_offset", offset + len(rows))
        return items


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_plan(plan, directory, data_nature):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Plan directory is not empty; choose a new directory to avoid replacing reviewed records")
    manifest = {key: value for key, value in plan.items() if key != "batches"}
    manifest["data_nature"] = data_nature
    manifest["batches"] = []
    for index, batch in enumerate(plan["batches"], 1):
        name = f"batch-{index:05d}.json"
        _write_json(directory / name, batch)
        manifest["batches"].append({"file": name, "batch_id": batch["batch_id"], "record_count": len(batch["records"]),
                                     "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest()})
    _write_json(directory / "plan.json", manifest)
    return manifest


def load_plan(directory):
    directory = Path(directory)
    manifest = strict_json((directory / "plan.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "liangzihu-import-plan/1":
        raise ValueError("Unsupported import plan format")
    profile = load_profile(manifest["source_id"])
    if digest(profile) != manifest["profile_hash"]:
        raise ValueError("Installed adapter artifacts changed after planning; regenerate the plan")
    batches = []
    for item in manifest["batches"]:
        name = item["file"]
        if Path(name).name != name or not name.startswith("batch-") or not name.endswith(".json"):
            raise ValueError("Unsafe batch filename")
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Batch content changed after planning: " + name)
        batch = strict_json(raw.decode("utf-8"))
        if any(batch[key] != manifest[key] for key in ("source_id", "profile_id", "version", "observed_at", "data_nature")) or batch["batch_id"] != item["batch_id"]:
            raise ValueError("Batch identity does not match the reviewed plan")
        batches.append(batch)
    if len(batches) != manifest["batch_count"]:
        raise ValueError("Plan batch count mismatch")
    return manifest, batches


def send_batch(client, batch, *, apply=False, install=False):
    if install:
        payload = load_bundle(batch["source_id"])
        payload["batch"] = batch
        route = "/api/v1/integration/bundles" + ("" if apply else "/preview")
    else:
        payload = batch
        route = "/api/v1/integration/batches" if apply else "/api/v1/integration/preview"
    return client.request(route, payload, key="lzhu-" + digest(payload) if apply else None)


def apply_plan(client, directory, *, apply=False, install=False):
    """Replay unchanged requests. Each batch is atomic; the complete plan is not.

    The default is a local reviewed-plan check, not a false claim that remote
    preview could see the previous rolled-back batch. Apply preflights each next
    batch after earlier commits; a failure stops immediately and remains resumable.
    """
    manifest, batches = load_plan(directory)
    if not apply:
        return {"read_only": True, "validation": "plan_files_and_hashes_only", "remote_preflight": "not_run",
                "batch_count": len(batches), "record_count": manifest["record_count"], "data_nature": manifest["data_nature"],
                "next_step": "Use --apply after review; each batch is previewed immediately before commit"}
    completed = []
    for index, batch in enumerate(batches, 1):
        # Replaying after a transport failure must send the exact original request;
        # the backend batch/idempotency guard recognizes already committed content.
        send_batch(client, batch, apply=False, install=install and index == 1)
        result = send_batch(client, batch, apply=True, install=install and index == 1)
        receipt = Path(directory) / (f"receipt-{index:05d}.json")
        _write_json(receipt, result)
        completed.append(batch["batch_id"])
        _write_json(Path(directory) / "progress.json", {"plan_id": manifest["plan_id"], "completed_batches": completed,
                                                       "atomicity": "each_batch_only", "data_nature": manifest["data_nature"]})
    return {"applied": True, "batch_count": len(completed), "record_count": manifest["record_count"],
            "atomicity": "each_batch_only", "receipts_directory": str(Path(directory).resolve()), "data_nature": manifest["data_nature"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["coverage", "install-definitions", "preview", "plan", "apply-plan"])
    parser.add_argument("--source-id", help="Stable upstream installation identifier; never a generated entity UUID")
    parser.add_argument("--input", type=Path, help="JSON envelope/array or JSONL exported source records")
    parser.add_argument("--observed-at", help="Actual source snapshot timestamp with timezone")
    parser.add_argument("--batch-id", help="Stable ID for this exact request, reused on retry")
    parser.add_argument("--data-nature", choices=["production", "synthetic", "test"], help="Required for raw arrays/JSONL")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--apply", action="store_true", help="Explicitly commit approved input")
    parser.add_argument("--install-definitions", action="store_true", help="Atomically install 18 reviewed packages and the profile with the first batch")
    parser.add_argument("--output-dir", type=Path, help="Plan/receipts directory; use implementation/runtime/source-imports/ for real records")
    parser.add_argument("--plan-dir", type=Path, help="Directory containing plan.json for apply-plan")
    parser.add_argument("--bindings", type=Path, help="Authenticated source binding snapshot JSON instead of fetching it")
    parser.add_argument("--fetch-bindings", action="store_true", help="Read current source bindings to plan incremental updates")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.apply and args.command in {"coverage", "plan"}:
            raise ValueError("This command is read-only; --apply is only valid for preview, install-definitions or apply-plan")
        if args.command == "coverage":
            result = strict_json((DIRECTORY / "artifact-manifest.json").read_text(encoding="utf-8"))
        elif args.command == "apply-plan":
            if not args.plan_dir:
                raise ValueError("--plan-dir is required")
            client = ApiClient(args.base_url, os.environ.get("AGRI_API_TOKEN")) if args.apply else None
            result = apply_plan(client, args.plan_dir, apply=args.apply, install=args.install_definitions)
        else:
            profile = load_profile(args.source_id)
            if args.command == "install-definitions":
                payload = load_bundle(args.source_id)
                client = ApiClient(args.base_url, os.environ.get("AGRI_API_TOKEN"))
                result = client.request("/api/v1/integration/bundles" + ("" if args.apply else "/preview"), payload,
                                        key="lzhu-install-" + digest(payload) if args.apply else None)
                result = {"read_only": not args.apply, "package_count": result.get("package_count"), "table_count": result.get("table_count")}
            else:
                if not args.input:
                    raise ValueError("--input is required")
                records, metadata = read_records(args.input)
                source_commit = strict_json((DIRECTORY / "artifact-manifest.json").read_text(encoding="utf-8"))["source_commit"]
                if metadata.get("source_commit") and metadata["source_commit"] != source_commit:
                    raise ValueError("Input source_commit differs from the reviewed schema baseline; review the source mapping first")
                nature = args.data_nature or metadata.get("data_nature")
                if nature not in {"production", "synthetic", "test"}:
                    raise ValueError("Declare --data-nature production|synthetic|test; data origin is not inferred")
                if args.data_nature and metadata.get("data_nature") and args.data_nature != metadata["data_nature"]:
                    raise ValueError("Explicit data nature conflicts with the input envelope")
                observed_at = args.observed_at or metadata.get("observed_at")
                if args.command == "preview":
                    batch_id = args.batch_id or metadata.get("batch_id") or "lzhu-" + digest({"records": records, "observed_at": observed_at})
                    batch = make_batch(profile, records, observed_at, batch_id, nature)
                    client = ApiClient(args.base_url, os.environ.get("AGRI_API_TOKEN"))
                    response = send_batch(client, batch, apply=args.apply, install=args.install_definitions)
                    receipt_dir = args.output_dir or BASE / "runtime/source-imports/liangzihu-receipts" / digest(batch)[:24]
                    _write_json(receipt_dir / ("applied.json" if args.apply else "preview.json"), response)
                    result = {"read_only": not args.apply, "data_nature": nature, "record_count": len(records),
                              "counts": response.get("batch", response).get("counts"), "receipt_directory": str(receipt_dir.resolve())}
                else:
                    bindings = []
                    if args.bindings and args.fetch_bindings:
                        raise ValueError("Choose --bindings or --fetch-bindings, not both")
                    if args.bindings:
                        bindings_value = strict_json(args.bindings.read_text(encoding="utf-8-sig"))
                        bindings = bindings_value.get("items", []) if isinstance(bindings_value, dict) else bindings_value
                    elif args.fetch_bindings:
                        bindings = ApiClient(args.base_url, os.environ.get("AGRI_API_TOKEN")).bindings(args.source_id)
                    plan = plan_batches(profile, records, observed_at, existing_bindings=bindings, batch_size=args.batch_size, data_nature=nature)
                    directory = args.output_dir or BASE / "runtime/source-imports/liangzihu-plans" / plan["plan_id"]
                    saved = save_plan(plan, directory, nature)
                    result = {"read_only": True, "plan_id": saved["plan_id"], "data_nature": nature,
                              "record_count": saved["record_count"], "batch_count": saved["batch_count"],
                              "plan_directory": str(directory.resolve()), "validation": saved["validation"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"error": str(exc), "status": "stopped", "note": "For a multi-batch apply, earlier commits may exist; retain the plan and replay unchanged requests."}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
