"""Fenced import worker: immutable staging, complete verification, atomic release."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from .config import contained_path
from .importer import MODEL_VERSION, build_batch, canonical_hash, file_hash, input_mapping_hash, load_mapping
from .rdf import build_navigation, generate_rdf, load_and_verify, save_json, verify_files
from csv_batch_store import compare_rows, encoded, sql_type, typed_value


def _q(name):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name) or len(name.encode()) > 63:
        raise ValueError("Unsafe SQL identifier")
    return '"' + name + '"'


def _identity(batch):
    value = hashlib.sha256()
    for name in ("raw", "nodes", "relations"):
        value.update(name.encode() + b"\n")
        for row in batch["snapshot"][name]:
            value.update(encoded(row) + b"\n")
    return {"batch_id": batch["batch_id"], "source_sha256": batch["snapshot"]["package_sha256"],
            "mapping_sha256": batch["mapping"]["sha256"], "mapping_version": batch["mapping"]["version"],
            "schema_version": batch["mapping"]["schema_version"], "model_version": MODEL_VERSION,
            "schema_sha256": canonical_hash(batch["snapshot"]["schema"]), "snapshot_sha256": value.hexdigest()}


def _rowsets(batch):
    snapshot = batch["snapshot"]
    nodes = {row["node_id"]: row for row in snapshot["nodes"]}
    yield "source_tables", ["table_name", "definition"], ((name, spec) for name, spec in sorted(snapshot["schema"]["tables"].items())), '"table_name" COLLATE "C"'
    yield "field_dictionary", ["table_name", "field_name", "ordinal", "definition"], (
        (table, field, number, definition) for table, spec in sorted(snapshot["schema"]["tables"].items())
        for number, (field, definition) in enumerate(spec["columns"].items(), 1)), '"table_name" COLLATE "C","ordinal"'
    yield "raw_records", ["table_name", "row_number", "source_pk", "payload", "status", "issues", "sample_reason"], (
        tuple(row[key] for key in ("table_name", "row_number", "source_pk", "payload", "status", "issues", "sample_reason"))
        for row in snapshot["raw"]), '"table_name" COLLATE "C","row_number"'
    yield "ontology_nodes", ["node_id", "table_name", "source_pk", "source_row", "properties", "nature", "role"], (
        tuple(row[key] for key in ("node_id", "table_name", "source_pk", "source_row", "properties", "nature", "role"))
        for row in sorted(snapshot["nodes"], key=lambda row: row["node_id"])), '"node_id"'
    yield "ontology_relations", ["edge_id", "from_node", "from_table", "field_name", "target_table", "target_pk", "to_node", "resolution", "source_row", "list_index", "evidence"], (
        (row["edge_id"], row["from_node"], nodes[row["from_node"]]["table_name"], row["field_name"], row["target_table"],
         row["target_pk"], row["to_node"], row["resolution"], row["source_row"], row.get("list_index"), row["evidence"])
        for row in snapshot["relations"]), '"edge_id"'
    for table, spec in sorted(snapshot["schema"]["tables"].items()):
        fields = list(spec["columns"])

        def values(table=table, spec=spec, fields=fields):
            for row in sorted((node for node in snapshot["nodes"] if node["table_name"] == table), key=lambda node: node["source_pk"]):
                yield tuple(typed_value(row["properties"][field], spec["columns"][field]) for field in fields) + (
                    row["node_id"], row["source_row"], row["nature"])

        yield "data_" + table, fields + ["_node_id", "_source_row", "_data_nature"], values(), '"id" COLLATE "C"'


def _physical(connection, schema):
    columns = connection.execute('''SELECT c.relname,a.attnum,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
        WHERE n.nspname=%s AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname COLLATE "C",a.attnum''', (schema,)).fetchall()
    constraints = connection.execute('''SELECT c.relname,k.conname,k.contype,pg_catalog.pg_get_constraintdef(k.oid)
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s
        ORDER BY c.relname COLLATE "C",k.conname COLLATE "C"''', (schema,)).fetchall()
    return canonical_hash({"columns": columns, "constraints": constraints})


def store_batch(config, store, batch, *, progress=None):
    """Create a new schema once; every retry reads all rows and refuses repairs."""
    from psycopg.rows import tuple_row
    from psycopg.types.json import Jsonb
    from psycopg.conninfo import conninfo_to_dict

    emit = progress or (lambda value: None)
    schema = batch["snapshot"]["source_schema"]
    if not re.fullmatch(r"ls_batch_[0-9a-f]{24}", schema):
        raise ValueError("SQL batch schema is outside the new deployment namespace")
    q = lambda name: _q(schema) + "." + _q(name)
    identity = _identity(batch)
    with store.connect() as connection:
        connection.row_factory = tuple_row
        with connection.transaction():
            target = connection.execute("SELECT inet_server_port(), current_database()").fetchone()
            if target[0] == 25449:
                raise ValueError("Migration source PostgreSQL is never writable")
            lock = int(batch["batch_id"][:15], 16)
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
            exists = connection.execute("SELECT to_regnamespace(%s)", (schema,)).fetchone()[0] is not None
            if not exists:
                emit({"stage": "sql_create", "schema": schema})
                connection.execute("CREATE SCHEMA " + _q(schema))
                statements = {
                    "metadata": '"key" TEXT PRIMARY KEY,"document" JSONB NOT NULL',
                    "source_tables": '"table_name" TEXT PRIMARY KEY,"definition" JSONB NOT NULL',
                    "field_dictionary": '"table_name" TEXT NOT NULL,"field_name" TEXT NOT NULL,"ordinal" INTEGER NOT NULL,"definition" JSONB NOT NULL,PRIMARY KEY("table_name","field_name"),FOREIGN KEY("table_name") REFERENCES ' + q("source_tables") + '("table_name")',
                    "raw_records": '"table_name" TEXT NOT NULL,"row_number" BIGINT NOT NULL CHECK("row_number">0),"source_pk" TEXT NOT NULL,"payload" JSONB NOT NULL,"status" TEXT NOT NULL,"issues" JSONB NOT NULL,"sample_reason" TEXT NOT NULL,PRIMARY KEY("table_name","row_number"),FOREIGN KEY("table_name") REFERENCES ' + q("source_tables") + '("table_name")',
                    "ontology_nodes": '"node_id" UUID PRIMARY KEY,"table_name" TEXT NOT NULL,"source_pk" TEXT NOT NULL,"source_row" BIGINT NOT NULL,"properties" JSONB NOT NULL,"nature" TEXT NOT NULL,"role" TEXT NOT NULL,UNIQUE("table_name","source_pk"),UNIQUE("node_id","table_name","source_pk"),UNIQUE("node_id","table_name","source_row"),FOREIGN KEY("table_name","source_row") REFERENCES ' + q("raw_records") + '("table_name","row_number")',
                    "ontology_relations": '"edge_id" BIGINT PRIMARY KEY,"from_node" UUID NOT NULL,"from_table" TEXT NOT NULL,"field_name" TEXT NOT NULL,"target_table" TEXT NOT NULL,"target_pk" TEXT NOT NULL,"to_node" UUID,"resolution" TEXT NOT NULL,"source_row" BIGINT NOT NULL,"list_index" BIGINT,"evidence" TEXT NOT NULL,FOREIGN KEY("from_node","from_table","source_row") REFERENCES ' + q("ontology_nodes") + '("node_id","table_name","source_row"),FOREIGN KEY("to_node","target_table","target_pk") REFERENCES ' + q("ontology_nodes") + '("node_id","table_name","source_pk"),CHECK(("resolution"=\'resolved\' AND "to_node" IS NOT NULL) OR ("resolution"=\'unresolved\' AND "to_node" IS NULL))'
                }
                for name, definition in statements.items():
                    connection.execute("CREATE TABLE " + q(name) + " (" + definition + ")")
                for table, spec in sorted(batch["snapshot"]["schema"]["tables"].items()):
                    fields = [_q(field) + " " + sql_type(definition) + (" PRIMARY KEY" if field == "id" else "")
                              for field, definition in spec["columns"].items()]
                    fields += ['"_node_id" UUID NOT NULL UNIQUE REFERENCES ' + q("ontology_nodes") + '("node_id")',
                               '"_source_row" BIGINT NOT NULL', '"_data_nature" TEXT NOT NULL']
                    connection.execute("CREATE TABLE " + q("data_" + table) + " (" + ",".join(fields) + ")")
                connection.execute("CREATE INDEX ON " + q("ontology_relations") + '("from_node")')
                connection.execute("CREATE INDEX ON " + q("ontology_relations") + '("to_node")')
                for name, fields, rows, _ in _rowsets(batch):
                    copied = 0
                    with connection.cursor() as cursor:
                        with cursor.copy("COPY " + q(name) + " (" + ",".join(_q(field) for field in fields) + ") FROM STDIN") as copier:
                            for row in rows:
                                copier.write_row(tuple(Jsonb(value) if isinstance(value, (dict, list)) else value for value in row))
                                copied += 1
                                if copied % 2000 == 0:
                                    emit({"stage": "sql_copy", "table": name, "rows": copied})
                    emit({"stage": "sql_copy", "table": name, "rows": copied})
                identity["physical_sha256"] = _physical(connection, schema)
                connection.execute("INSERT INTO " + q("metadata") + ' VALUES (%s,%s)', ("batch", Jsonb(identity)))
                api_user = conninfo_to_dict(config.sql["api_dsn"]).get("user")
                if api_user:
                    from psycopg import sql
                    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(api_user)))
                    for name, _, _, _ in _rowsets(batch):
                        if name != "raw_records":
                            connection.execute(sql.SQL("GRANT SELECT ON {}.{} TO {}").format(sql.Identifier(schema), sql.Identifier(name), sql.Identifier(api_user)))
            stored = connection.execute("SELECT key,document FROM " + q("metadata") + " ORDER BY key").fetchall()
            if len(stored) != 1 or stored[0][0] != "batch" or any(stored[0][1].get(k) != v for k, v in identity.items()):
                raise ValueError("Existing SQL batch identity differs; refusing overwrite")
            if _physical(connection, schema) != stored[0][1].get("physical_sha256"):
                raise ValueError("SQL physical schema readback differs")
            checks = []
            for number, (name, fields, expected, ordering) in enumerate(_rowsets(batch)):
                with connection.cursor(name="ls_read_" + str(number)) as cursor:
                    cursor.itersize = 2000
                    cursor.execute("SELECT " + ",".join(_q(field) for field in fields) + " FROM " + q(name) + " ORDER BY " + ordering)
                    report = compare_rows(expected, cursor, name)
                checks.append(report)
                emit({"stage": "sql_readback", "table": name, "status": report["status"]})
            if any(report["status"] != "passed" for report in checks):
                raise ValueError("Complete SQL batch row readback differs")
            emit({"stage": "sql_verified", "schema": schema})
    return {"status": "passed", "schema": schema, "identity": identity, "checks": checks,
            "schema_created": not exists, "all_rows_verified": True}


def process_job(config, store, job, worker_id):
    job_id, token = job.get("job_id", job.get("id")), job["lease_token"]
    UUID(job_id)
    last = [0.0, None]
    heartbeat_interval = min(10, config.limits.get("lease_seconds", 120) / 3)

    def progress(value):
        stage, now = value.get("stage", "processing"), time.monotonic()
        if stage != last[1] or now - last[0] > heartbeat_interval:
            store.heartbeat(job_id, worker_id, token, stage=stage, progress=value)
            last[:] = [now, stage]
            if not store.check_lease(job_id, worker_id, token):
                raise RuntimeError("Import worker lease expired")

    try:
        progress({"stage": "validate_input"})
        mapping = load_mapping(config.mapping_file)
        source = contained_path(config.data_dir, job["source_path"])
        if (file_hash(source) != job["source_sha256"] or input_mapping_hash(mapping, source.name) != job["mapping_sha256"]
                or str(job.get("schema_version", "1")) != str(mapping["schema_version"])):
            raise ValueError("Queued source or mapping hash/version changed")
        free = shutil.disk_usage(config.data_dir).free
        if free < config.limits.get("min_free_disk_bytes", 1024 ** 3) + source.stat().st_size * 10:
            raise ValueError("Insufficient disk space for bounded import staging")
        work = (Path(config.data_dir) / "imports" / job_id / ("lease-" + str(int(token)))).resolve()
        if not work.is_relative_to(Path(config.data_dir).resolve()):
            raise ValueError("Import staging path escapes private storage")
        batch = build_batch(source, work / "input", mapping, config.limits)
        if batch["snapshot"]["package_sha256"] != job["source_sha256"]:
            raise ValueError("Retained original source hash differs from the queued job")
        save_json(work / "input-manifest.json", batch["manifest"])
        save_json(work / "model-report.json", batch["model"])
        progress({"stage": "sql_staging", "batch_id": batch["batch_id"]})
        sql_proof = store_batch(config, store, batch, progress=progress)
        if sql_proof.get("status") != "passed":
            raise ValueError("SQL staging was not verified")
        save_json(work / "sql-readback.json", sql_proof)
        progress({"stage": "rdf_generation"})
        generated = generate_rdf(batch, work / "rdf", progress=progress)
        progress({"stage": "rdf_upload"})
        rdf_proof = load_and_verify(config, generated, progress=progress)
        save_json(work / "rdf-readback.json", rdf_proof)
        progress({"stage": "navigation_and_shacl"})
        navigation = build_navigation(batch, generated, rdf_proof, work / "public", progress=progress)
        progress({"stage": "verify_files"})
        verify_files(navigation["data_dir"], navigation["files"])
        def reference(path):
            return contained_path(config.data_dir, path).relative_to(Path(config.data_dir).resolve()).as_posix()

        release = {**_identity(batch), "sql_schema": batch["snapshot"]["source_schema"], "path_base": "data",
                   "rdf_graph": rdf_proof["graph_iri"], "namespace": batch["namespace"],
                   "navigation_dir": reference(navigation["data_dir"]), "manifest_path": reference(navigation["manifest_path"]),
                   "navigation": {"manifest_path": reference(navigation["manifest_path"]),
                                  "data_dir": reference(navigation["data_dir"]), "files": navigation["files"]},
                   "counts": navigation["counts"], "source_path": reference(batch["original_path"]),
                   "verification": {"sql": sql_proof, "rdf": rdf_proof, "shacl": navigation["shacl"], "files": "passed"},
                   "data_nature": "imported_unverified", "raw_payload_public": False, "read_only": False}
        progress({"stage": "publish"})
        kwargs = {"job_id": job_id, "worker_id": worker_id, "lease_token": token}
        registered = store.register_release(release, **kwargs)
        published = store.publish_release(registered["release_id"], **kwargs)
        store.finish_job(job_id, worker_id, token, result={"release_id": published["release_id"], "batch_id": batch["batch_id"]})
        return published
    except Exception as error:
        if store.check_lease(job_id, worker_id, token):
            store.fail_job(job_id, worker_id, token, {"code": "import_failed", "message": "Import failed at " + str(last[1]),
                                                     "exception_type": type(error).__name__}, retryable=not isinstance(error, (ValueError, PermissionError)))
        raise


def run_worker(config, once=False):
    from .store import Store
    worker_id = "worker-" + str(uuid4())
    store = Store(config, role="worker")
    while True:
        job = store.claim_job(worker_id)
        if job is not None:
            try:
                result = process_job(config, store, job, worker_id)
            except Exception as error:
                result = {"job_id": job.get("job_id", job.get("id")), "status": "failed", "exception_type": type(error).__name__}
            if once:
                return result
        elif once:
            return None
        else:
            time.sleep(min(5, config.limits.get("worker_poll_seconds", 1)))
