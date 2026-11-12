"""One explicit configuration for local HTTP, worker and private recovery."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .config import Config, contained_path


def build_parser():
    parser = argparse.ArgumentParser(description="梁子湖本地本体服务器")
    parser.add_argument("--config", required=True, help="JSON 配置文件")
    parser.add_argument("--env-file", help="私有环境文件；默认读取配置中的 env_file")
    commands = parser.add_subparsers(dest="command", required=True)
    for operation in ("init", "start", "stop", "restart", "status", "serve", "supervise", "open"):
        commands.add_parser(operation)
    retry = commands.add_parser("retry-job")
    retry.add_argument("job_id")
    worker = commands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    backup = commands.add_parser("backup")
    backup.add_argument("destination")
    backup.add_argument("--options", required=True, help="私有源配置 JSON，连接用环境变量名")
    backup.add_argument("--writers-stopped", action="store_true", help="确认本服务与所有外部源写入者已停止")
    verify = commands.add_parser("verify-backup")
    verify.add_argument("manifest")
    restore = commands.add_parser("restore")
    restore.add_argument("manifest")
    restore.add_argument("--options", required=True, help="显式新空目标的私有 JSON 配置")
    placement=commands.add_parser("place-restored-assets")
    placement.add_argument("manifest")
    placement.add_argument("--options",required=True,help="含恢复 staging 与显式 asset_placement 的私有 JSON")
    bootstrap = commands.add_parser("bootstrap-release")
    bootstrap.add_argument("--proof", required=True, help="现有快照迁移验证证明 JSON")
    bootstrap.add_argument("--replace-active", action="store_true", help="显式批准替换已有 active release")
    return parser


def load_config(path, env_file=None):
    path = Path(path).resolve()
    # The private env file is never copied into runtime state, public assets,
    # backups, command arguments or output.
    if env_file is None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            env_file = payload.get("env_file")
        except (OSError, ValueError):
            env_file = None
    if env_file:
        from dotenv import load_dotenv
        private = (path.parent / env_file).resolve()
        if not private.is_file():
            raise ValueError("Private environment file is unavailable")
        load_dotenv(private, override=False)
    return Config.load(path)


def _options(path):
    """Resolve only declared env references; never recursively rewrite IRIs."""
    options_path = Path(path).resolve()
    value = json.loads(options_path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Options must be an object")
    database_env = value.pop("database_env", None)
    if database_env is not None:
        if not isinstance(database_env, dict):
            raise ValueError("database_env must map labels to environment names")
        value["databases"] = {}
        for label, variable in database_env.items():
            dsn = os.environ.get(variable, "")
            if not dsn:
                raise ValueError("Backup/restore connection environment variable missing")
            value["databases"][label] = dsn
    for key in ("pg_bin", "asset_destination"):
        if key in value:
            value[key] = str((options_path.parent / value[key]).absolute() if key=="asset_destination" else (options_path.parent / value[key]).resolve())
    if "assets" in value:
        value["assets"] = {label: str((options_path.parent / reference).resolve()) for label, reference in value["assets"].items()}
    return value


def bootstrap_release(config, proof_path, *, replace_active=False):
    from .store import Store
    from .query import QueryService
    from .rdf import verify_files
    store = Store(config, role="admin")
    if store.active_release() and not replace_active:
        raise ValueError("An active release already exists")
    proof = json.loads(Path(proof_path).read_text(encoding="utf-8-sig"))
    manifest_source = contained_path(config.review_dir, "data/manifest.json")
    manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
    graphs = manifest.get("rdf_graphs")
    if (proof.get("status") != "passed" or not isinstance(graphs, list) or not graphs
            or set(proof.get("rdf_graphs", [])) != set(graphs)
            or proof.get("raw_payload_public") is not False
            or not isinstance(proof.get("sql_schemas"), list) or not proof["sql_schemas"]
            or proof.get("sql_verified") is not True or proof.get("rdf_verified") is not True):
        raise ValueError("Complete verified SQL/RDF migration proof is required")
    if not all(re.fullmatch(r"[a-z][a-z0-9_]*", schema) for schema in proof["sql_schemas"]):
        raise ValueError("Invalid verified SQL schema")
    with store.connect() as connection:
        present = {row["schema_name"] for row in connection.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
        if set(proof["sql_schemas"]) - present:
            raise ValueError("Verified source SQL schema is absent on configured target")
    release_id = str(uuid4())
    destination = contained_path(config.data_dir, "releases", release_id)
    # Snapshot is copied privately and hashed. The active pointer is changed
    # only after the new target's graphs and every navigation file pass.
    destination.mkdir(parents=True)
    files = {}
    for path in sorted((config.review_dir / "data").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(config.review_dir).as_posix()
        if not (relative == "data/manifest.json" or relative == "data/map-features.json" or re.fullmatch(r"data/(classes|details|relations)/[A-Za-z0-9_./-]+\.json(?:\.gz)?", relative)):
            continue
        source = contained_path(config.review_dir, relative)
        target = contained_path(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files[relative] = {"bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    verify_files(destination, files)
    base = destination.relative_to(config.data_dir).as_posix()
    release = {"release_id": release_id, "path_base": "data", "legacy_snapshot": True,
        "navigation_dir": base, "manifest_path": base+"/data/manifest.json",
        "navigation": {"data_dir": base, "manifest_path": base+"/data/manifest.json", "files": files},
        "namespace": manifest["namespace"], "rdf_graphs": graphs,
        "sql_schemas": proof["sql_schemas"], "counts": manifest.get("counts", {}),
        "package_sha256": manifest.get("package_sha256"), "data_nature": proof.get("data_nature", "mixed_review_data"), "read_only": True,
        "raw_payload_public": False, "verification": {"sql": "migration-proof-passed", "rdf": "migration-proof-passed", "files": "passed"}}
    if not QueryService(config, release).status()["available"]:
        raise ValueError("Configured target does not contain the verified RDF graphs")
    registered = store.register_release(release)
    return store.publish_release(registered["release_id"])


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config, args.env_file)
        from . import lifecycle
        if args.command in ("serve","worker","supervise","bootstrap-release") and (config.data_dir/"asset-placement.pending.json").exists():
            raise lifecycle.LifecycleError("ASSET_PLACEMENT_REQUIRED","恢复资产尚未对齐或校验失败；请先完成 place-restored-assets，保持服务停止")
        if args.command == "init":
            from .store import Store
            lifecycle.NativeServices(config).start()
            config.data_dir.mkdir(parents=True, exist_ok=True)
            for name in ("uploads", "imports", "releases", "runtime"):
                contained_path(config.data_dir, name).mkdir(exist_ok=True)
            Store(config, role="admin").ensure_schema()
            result = {"status": "initialized", "automatic_boot": "not-installed"}
        elif args.command == "start":
            result = lifecycle.start(config)
        elif args.command == "stop":
            result = lifecycle.stop(config)
        elif args.command == "restart":
            lifecycle.stop(config)
            result = lifecycle.start(config)
        elif args.command == "status":
            result = lifecycle.status(config)
        elif args.command == "open":
            import webbrowser
            host = "[::1]" if config.host == "::1" else "127.0.0.1" if config.host == "0.0.0.0" else config.host
            url = f"http://{host}:{config.port}/"
            result = {"status": "opened" if webbrowser.open(url) else "open_manually", "url": url}
        elif args.command == "retry-job":
            from .store import Store
            from .http import public_job
            result = public_job(Store(config, role="worker").retry_job(args.job_id))
        elif args.command == "serve":
            from .http import serve
            serve(config)
            return 0
        elif args.command == "supervise":
            lifecycle.supervise(config)
            return 0
        elif args.command == "worker":
            from .worker import run_worker
            result = run_worker(config, once=args.once)
        elif args.command == "backup":
            from .backup import create_backup
            if lifecycle.status(config)["status"] != "stopped":
                raise ValueError("Stop owned HTTP and worker before backup")
            options = _options(args.options)
            options["writers_stopped"] = args.writers_stopped
            if not args.writers_stopped:
                raise ValueError("Explicit writer-stop confirmation is required")
            native = lifecycle.NativeServices(config)
            native.start()
            try:
                path = create_backup(config, args.destination, source_options=options)
            finally:
                native.stop()
            result = {"status": "created", "manifest_path": str(path)}
        elif args.command == "verify-backup":
            from .backup import verify_backup
            result = verify_backup(args.manifest)
        elif args.command == "restore":
            from .backup import restore_backup
            if lifecycle.status(config)["status"] != "stopped":
                raise ValueError("Stop owned HTTP and worker before restore")
            native = lifecycle.NativeServices(config)
            native.start()
            try:
                options=_options(args.options)
                lifecycle.atomic_json(config.data_dir/"asset-placement.pending.json",{"status":"restore_or_asset_placement_pending"})
                result = restore_backup(config, args.manifest, target_options=options)
                lifecycle.atomic_json(config.data_dir/"asset-placement.pending.json",{"status":"asset_placement_pending","backup_id":result["backup_id"]})
                result["asset_placement_required"]=True
            finally:
                native.stop()
        elif args.command == "place-restored-assets":
            from .backup import place_restored_assets
            if lifecycle.status(config)["status"] != "stopped":
                raise ValueError("Stop owned HTTP and worker before placing restored assets")
            with lifecycle._start_lock(config):
                result=place_restored_assets(config,args.manifest,target_options=_options(args.options))
        elif args.command == "bootstrap-release":
            from .query import public_release
            result = public_release(bootstrap_release(config, args.proof, replace_active=args.replace_active))
        else:
            raise ValueError("Unknown command")
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        # Library exceptions can contain DSNs, file names or raw cells. The CLI
        # has the same sanitized boundary as HTTP; no traceback by default.
        from .lifecycle import LifecycleError
        from .backup import BackupError
        safe_backup=isinstance(error,BackupError) and re.fullmatch(r"[A-Z0-9_]+",str(error))
        code = error.code if isinstance(error, LifecycleError) else str(error) if safe_backup else "COMMAND_FAILED"
        message = str(error) if isinstance(error, LifecycleError) else "备份、恢复或资产对齐失败；请检查错误码和私有报告，保持服务停止" if safe_backup else "命令失败；请检查配置、服务状态及命令所需条件"
        print(json.dumps({"error": {"code": code, "message": message, "request_id": str(uuid4()), "retryable": False}}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
