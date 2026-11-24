"""Isolated native CSV/ZIP latency benchmark; never uses a default deployment.

Prepare a fresh target with --data-dir and explicit native tool paths, or run an
unused prepared target with --config. Every run requires its own ownership
marker and empty application databases. Private credentials/logs remain under
.runtime. The output JSON contains synthetic data measurements only.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from functools import wraps
import hashlib
from http.server import ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import platform
import stat
import statistics
import sys
import threading
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx
from psycopg.conninfo import conninfo_to_dict

PROTECTED_PORTS = {8792, 25459, 23059, 25449, 23049}
MARKER = "benchmark-target.json"
CONTRACT = "local-server-latency/1"
STAGES = ("build_batch", "store_batch", "generate_rdf", "load_and_verify",
          "build_navigation", "verify_files", "submit_job", "claim_job",
          "register_release", "publish_release", "finish_job")


def reject_indirect_libpq_environment(environ=None):
    environment = os.environ if environ is None else environ
    if any(environment.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")):
        raise ValueError("Indirect libpq environment is forbidden for the benchmark")


def private_diagnostic(config, phase, error):
    """Runtime-only traceback, never stdout/public JSON, never stack locals."""
    import traceback
    try:
        with (config.data_dir / "benchmark-diagnostics.log").open("a", encoding="utf-8") as stream:
            stream.write(datetime.now(timezone.utc).isoformat() + " " + phase + "\n")
            stream.writelines(traceback.TracebackException.from_exception(error, capture_locals=False).format())
            stream.write("\n")
    except OSError:
        # A secondary log failure must not replace the actual sample failure.
        pass


def _safe_path(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.exists():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Benchmark paths must not use links or junctions")
    return path.resolve()


def _ports(ports):
    if (len(ports) != 3 or len(set(ports)) != 3 or
            any(isinstance(p, bool) or not isinstance(p, int) or p in PROTECTED_PORTS or not 1024 <= p <= 65535 for p in ports)):
        raise ValueError("Benchmark ports must be distinct and outside protected targets")


def _runtime_data(root, data):
    root, data = _safe_path(root), _safe_path(data)
    if data == root / ".runtime" or not data.is_relative_to(root / ".runtime"):
        raise ValueError("Benchmark data must be a separate child of the project .runtime")
    return root, data


def validate_new_run(root, data, ports):
    """Pure checks happen before provisioning creates anything."""
    _ports(ports)
    root, data = _runtime_data(root, data)
    if data.exists():
        raise ValueError("A benchmark requires a new, nonexistent data directory")
    return root, data


def validate_config_targets(config):
    root, data = _runtime_data(config.root, config.data_dir)
    if _safe_path(config.config_path).parent != data or config.host != "127.0.0.1":
        raise ValueError("Benchmark config and HTTP host must belong to the isolated target")
    if config.runtime.get("managed_postgres") is not True or config.runtime.get("managed_fuseki") is not True:
        raise ValueError("Benchmark requires both services managed in its own directory")
    pg_port, rdf_port = config.runtime.get("pg_port"), config.runtime.get("fuseki_port")
    _ports((config.port, pg_port, rdf_port))
    identities = []
    for role in ("admin", "api", "worker"):
        try:
            dsn = conninfo_to_dict(config.sql[role + "_dsn"])
        except Exception:
            raise ValueError("Benchmark SQL connection is invalid") from None
        if (dsn.get("host") != "127.0.0.1" or dsn.get("port") != str(pg_port) or
                not dsn.get("dbname") or any(key in dsn for key in ("service", "hostaddr", "options"))):
            raise ValueError("Benchmark SQL roles must target the explicit managed loopback instance")
        identities.append((dsn["host"], dsn["port"], dsn["dbname"]))
    if len(set(identities)) != 1:
        raise ValueError("Benchmark SQL roles must use the same database")
    rdf = urlsplit(config.fuseki_url)
    if (rdf.scheme != "http" or rdf.hostname != "127.0.0.1" or rdf.port != rdf_port or
            rdf.path != "/fish_l1" or rdf.username or rdf.password or rdf.query or rdf.fragment):
        raise ValueError("Benchmark RDF URL must use its managed loopback dataset")
    paths = []
    for key in ("pg_data_dir", "fuseki_state_dir"):
        path = _safe_path(data / config.runtime[key])
        if not path.is_relative_to(data) or path == data:
            raise ValueError("Native data path escapes the isolated benchmark directory")
        paths.append(path)
    if paths[0].is_relative_to(paths[1]) or paths[1].is_relative_to(paths[0]):
        raise ValueError("Benchmark SQL and RDF data directories must be separate")
    return identities[0]


def validate_database_identity(config, actual_directory, database, port):
    identity = validate_config_targets(config)
    expected = _safe_path(Path(config.data_dir) / config.runtime["pg_data_dir"])
    if _safe_path(actual_directory) != expected or database != identity[2] or str(port) != identity[1]:
        raise ValueError("Read-only PostgreSQL identity differs from the benchmark target")


def summarize_samples(samples):
    values = sorted(float(row["elapsed_seconds"]) for row in samples if row["status"] == "passed")
    return {"attempts": len(samples), "successes": len(values), "failures": sum(row["status"] == "failed" for row in samples),
            "N": len(values), "small_sample": len(values) < 20,
            "p50_seconds": statistics.median(values) if values else None,
            "p95_seconds": values[math.ceil(.95 * len(values)) - 1] if values else None,
            "p95_method": "nearest-rank over successful samples; failures retained separately"}


def synthetic_package(relation_rows, nonce):
    if isinstance(relation_rows, bool) or not isinstance(relation_rows, int) or relation_rows < 1:
        raise ValueError("Relation row count must be positive")
    nonce = hashlib.sha256(str(nonce).encode()).hexdigest()[:24]
    farms = io.StringIO(newline="")
    ponds = io.StringIO(newline="")
    writer = csv.writer(farms, lineterminator="\n")
    writer.writerow(("id", "name", "is_synthetic"))
    writer.writerow(("farm-" + nonce, "Synthetic benchmark farm " + nonce, "true"))
    writer = csv.writer(ponds, lineterminator="\n")
    writer.writerow(("id", "farm_id", "name", "area_m2", "is_synthetic"))
    for number in range(relation_rows):
        writer.writerow((f"pond-{nonce}-{number:08d}", "farm-" + nonce, f"Synthetic pond {number}", number + 1, "true"))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in (("farms.csv", farms.getvalue()), ("ponds.csv", ponds.getvalue())):
            member = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, content)
    payload = output.getvalue()
    return payload, {"relation_rows": relation_rows, "source_rows": relation_rows + 1,
                     "nodes": relation_rows + 1, "input_bytes": len(payload),
                     "source_sha256": hashlib.sha256(payload).hexdigest(), "is_synthetic": True}


def _triple_key(subject, predicate, obj):
    from rdflib import BNode, Literal, URIRef
    from fish_rdf_sample import term_key
    if isinstance(obj, dict):
        kind, value = obj["type"], obj["value"]
        if kind == "uri":
            obj = URIRef(value)
        elif kind == "bnode":
            obj = BNode(value)
        elif kind in ("literal", "typed-literal"):
            obj = Literal(value, lang=obj.get("xml:lang") or None,
                          datatype=URIRef(obj["datatype"]) if obj.get("datatype") else None, normalize=False)
        else:
            raise ValueError("Unknown RDF object type")
    # Match the production inventory's RDF 1.1 term identity: plain strings
    # equal xsd:string, while numeric lexical forms and precision stay exact.
    # Synthetic benchmark graphs have no blank nodes, as enforced by term_key.
    return json.dumps([term_key(URIRef(subject)), term_key(URIRef(predicate)), term_key(obj)],
                      ensure_ascii=False, separators=(",", ":"))


@contextmanager
def _lexical_literals():
    """Preserve source terms, as in the production RDF readback verifier.

    Benchmark imports and reads run sequentially. These parser scopes run only
    after the worker completes; the HTTP serializer also uses normalize=False.
    """
    import rdflib
    prior = rdflib.NORMALIZE_LITERALS
    try:
        rdflib.NORMALIZE_LITERALS = False
        yield
    finally:
        rdflib.NORMALIZE_LITERALS = prior


def _fingerprint(keys):
    digest = hashlib.sha256()
    for key in sorted(keys):
        digest.update(key.encode("utf-8") + b"\n")
    return digest.hexdigest()


def _export_rows(response, fmt):
    if fmt == "json":
        return response.json()["items"]
    if fmt == "csv":
        rows = csv.DictReader(io.StringIO(response.text, newline=""))
        if rows.fieldnames != ["subject", "predicate", "value", "type", "datatype", "language"]:
            raise ValueError("Unexpected CSV export columns")
        return [{"subject": row["subject"], "predicate": row["predicate"], "object": {
            "value": row["value"], "type": row["type"], "datatype": row["datatype"], "xml:lang": row["language"]}} for row in rows]
    if fmt == "rdf":
        from rdflib import Graph
        class CaptureGraph(Graph):
            def __init__(self):
                super().__init__()
                self.received = []

            def add(self, triple):
                self.received.append(triple)
                return super().add(triple)
        graph = CaptureGraph()
        with _lexical_literals():
            graph.parse(data=response.text, format="turtle")
        return [{"subject": str(s), "predicate": str(p), "object": o} for s, p, o in graph.received]
    raise ValueError("Export format must be json, csv or rdf")


class ExportFailure(ValueError):
    def __init__(self, error_type, measurement):
        super().__init__("Complete export failed")
        self.error_type = error_type
        self.measurement = measurement


def complete_export(client, release_id, concept, fmt, page_size):
    started = perf_counter()
    progress = {"pages": 0, "bytes": 0, "triples": 0, "subjects": 0, "http_seconds": 0.0,
                "release_id": release_id, "format": fmt}
    try:
        return _complete_export(client, release_id, concept, fmt, page_size, progress)
    except Exception as error:
        progress["elapsed_seconds"] = perf_counter() - started
        raise ExportFailure(type(error).__name__, progress) from None


def _complete_export(client, release_id, concept, fmt, page_size, progress):
    started = perf_counter()
    cursor, cursors, keys, subjects = None, set(), set(), set()
    pages = size = 0
    http_seconds = 0.0
    while True:
        params = {"release_id": release_id, "class": concept, "format": fmt, "limit": page_size}
        if cursor:
            params["cursor"] = cursor
        before = perf_counter()
        response = client.get("/api/v1/export", params=params)
        http_seconds += perf_counter() - before
        size += len(response.content)
        progress.update(bytes=size, http_seconds=http_seconds)
        response.raise_for_status()
        if response.headers.get("X-Release-ID") != release_id:
            raise ValueError("Export header changed release")
        following = response.headers.get("X-Next-Cursor") or None
        if fmt == "json":
            body = response.json()
            if body.get("release_id") != release_id or (body.get("next_cursor") or None) != following:
                raise ValueError("Export body and header release/cursor disagree")
        rows = _export_rows(response, fmt)
        for row in rows:
            key = _triple_key(row["subject"], row["predicate"], row["object"])
            if key in keys:
                raise ValueError("Duplicate triple within or between export pages")
            keys.add(key)
            subjects.add(row["subject"])
        pages += 1
        progress.update(pages=pages, triples=len(keys), subjects=len(subjects))
        if not following:
            break
        if following in cursors or not rows or pages >= 1000000:
            raise ValueError("Export cursor cycle or incomplete page")
        cursors.add(following)
        cursor = following
    return {"pages": pages, "bytes": size, "triples": len(keys), "subjects": len(subjects),
            "termset_sha256": _fingerprint(keys), "http_seconds": http_seconds,
            "elapsed_seconds": perf_counter() - started, "release_id": release_id, "format": fmt}


def expected_export(generated_path, concept):
    """Independent untimed oracle from generated RDF, before any API export."""
    from rdflib import Graph, URIRef
    from rdflib.namespace import RDF
    with _lexical_literals():
        graph = Graph().parse(generated_path, format="nt")
    subjects = set(graph.subjects(RDF.type, URIRef(concept)))
    keys = set()
    for subject in subjects:
        for predicate, obj in graph.predicate_objects(subject):
            if ":raw:" in str(predicate) or str(predicate) == "http://www.w3.org/ns/prov#wasDerivedFrom":
                continue
            if isinstance(obj, URIRef) and any(token in str(obj) for token in (":source:", ":raw:", ":statement:", ":record:")):
                continue
            keys.add(_triple_key(subject, predicate, obj))
    return {"triples": len(keys), "subjects": len(subjects), "termset_sha256": _fingerprint(keys)}


class PipelineTiming:
    """Process-local wrappers; production modules/files remain unchanged."""
    def __init__(self):
        self.current = None
        self.lock = threading.RLock()
        self.originals = []

    def begin(self, sample):
        self.current = {"sample": sample, "stages": {}, "artifacts": {}, "done": threading.Event()}
        return self.current

    def _wrap(self, owner, name):
        original = getattr(owner, name)
        self.originals.append((owner, name, original))

        @wraps(original)
        def measured(*args, **kwargs):
            state = self.current
            start = perf_counter()
            result, error = None, None
            try:
                result = original(*args, **kwargs)
                return result
            except Exception as caught:
                error = type(caught).__name__
                raise
            finally:
                end = perf_counter()
                # A poll may start before the next HTTP submission. Associate
                # its returned job with the currently submitted sample.
                if name == "claim_job" and result is not None:
                    state = self.current
                if state is not None and not (name == "claim_job" and result is None and error is None):
                    with self.lock:
                        state["stages"].setdefault(name, []).append({"start": start, "end": end,
                            "elapsed_seconds": end - start, "status": "failed" if error else "passed",
                            **({"error_type": error} if error else {})})
                        if error is None and name in ("build_batch", "generate_rdf", "load_and_verify"):
                            state["artifacts"][name] = result
        setattr(owner, name, measured)

    def __enter__(self):
        from local_server import worker
        from local_server.store import Store
        for name in STAGES[:6]:
            self._wrap(worker, name)
        for name in STAGES[6:]:
            self._wrap(Store, name)
        return self

    def __exit__(self, *unused):
        for owner, name, original in reversed(self.originals):
            setattr(owner, name, original)

    def metrics(self, state, http_start):
        stages = state["stages"]
        result = {name + "_seconds": sum(item["elapsed_seconds"] for item in values) for name, values in stages.items()}
        def point(name, boundary):
            return stages[name][0 if boundary == "start" else -1][boundary]
        if "claim_job" in stages and "submit_job" in stages:
            result["queue_seconds"] = max(0.0, point("claim_job", "end") - point("submit_job", "end"))
        if "load_and_verify" in stages and "claim_job" in stages:
            result["import_processing_seconds"] = point("load_and_verify", "end") - point("claim_job", "end")
        if "publish_release" in stages and "build_navigation" in stages:
            result["publication_seconds"] = point("publish_release", "end") - point("build_navigation", "start")
            result["atomic_activation_seconds"] = result["publish_release_seconds"]
        if "finish_job" in stages:
            result["upload_to_complete_seconds"] = point("finish_job", "end") - http_start
        return result


@contextmanager
def _private_environment(path):
    """Only this target's newly generated env values can resolve its config."""
    from dotenv import dotenv_values
    from local_server.provision import SQL_ENV
    values = dotenv_values(path, interpolate=False)
    required = [*SQL_ENV.values(), "LZO_LOCAL_WRITE_TOKEN"]
    if any(not values.get(key) for key in required):
        raise ValueError("Benchmark private environment is incomplete")
    saved = {key: os.environ.get(key) for key in required}
    try:
        for key in required:
            os.environ[key] = values[key]
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def prepare_target(args):
    reject_indirect_libpq_environment()
    from local_server.lifecycle import atomic_json
    from local_server.provision import provision_fresh
    root, data = validate_new_run(args.root, args.data_dir, (args.http_port, args.pg_port, args.fuseki_port))
    result = provision_fresh(root, data, args.pg_bin, args.java_home, args.fuseki_home,
                             pg_port=args.pg_port, fuseki_port=args.fuseki_port, http_port=args.http_port)
    deployment = json.loads((data / "deployment.json").read_text(encoding="utf-8"))
    atomic_json(data / MARKER, {"contract": CONTRACT, "synthetic_only": True, "phase": "prepared",
                              "deployment_id": deployment["deployment_id"], "data_dir": str(data), "root": str(root)})
    return Path(result["config_path"])


def load_target(path):
    reject_indirect_libpq_environment()
    from local_server.config import Config
    path = _safe_path(path)
    marker = json.loads((path.parent / MARKER).read_text(encoding="utf-8"))
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    root, data = _runtime_data(payload["root"], payload["data_dir"])
    deployment = json.loads((data / "deployment.json").read_text(encoding="utf-8"))
    if (path.parent != data or marker.get("contract") != CONTRACT or marker.get("synthetic_only") is not True or
            marker.get("phase") != "prepared" or marker.get("deployment_id") != deployment.get("deployment_id") or
            _safe_path(marker.get("data_dir", ".")) != data or _safe_path(marker.get("root", ".")) != root or
            payload.get("env_file") != "private.env"):
        raise ValueError("An unused benchmark ownership marker is required")
    # Reject inline credentials or unusual env aliases before reading any env.
    from local_server.provision import SQL_ENV
    for role, variable in SQL_ENV.items():
        if payload["sql"].get(role + "_dsn_env") != variable or role + "_dsn" in payload["sql"]:
            raise ValueError("Benchmark must use its freshly provisioned environment")
    if payload.get("auth", {}).get("write_token_env") != "LZO_LOCAL_WRITE_TOKEN":
        raise ValueError("Benchmark token must belong to its private environment")
    private = _safe_path(data / "private.env")
    if private.parent != data:
        raise ValueError("Benchmark environment escapes its target")
    with _private_environment(private):
        config = Config.load(path)
    validate_config_targets(config)
    return config, marker


def _empty_database_identity(config):
    import psycopg
    with psycopg.connect(config.sql["admin_dsn"], connect_timeout=10, options="-c default_transaction_read_only=on") as connection:
        directory = connection.execute("SHOW data_directory").fetchone()[0]
        database, port = connection.execute("SELECT current_database(), inet_server_port()").fetchone()
        validate_database_identity(config, directory, database, port)
        schemas = connection.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public','information_schema') AND nspname NOT LIKE 'pg_%'").fetchall()
        tables = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]
        if schemas or tables:
            raise ValueError("Benchmark database already has application content")


def _worker_loop(config, timing, stop):
    from local_server.store import Store
    from local_server.worker import process_job
    store, identifier = Store(config, role="worker"), "benchmark-worker-" + str(uuid4())
    while not stop.is_set():
        try:
            job = store.claim_job(identifier)
        except Exception as error:
            private_diagnostic(config, "worker-claim", error)
            if timing.current:
                timing.current["worker_error"] = type(error).__name__
                timing.current["done"].set()
            return
        if job is None:
            stop.wait(config.limits.get("worker_poll_seconds", 1))
            continue
        state = timing.current
        try:
            state["release"] = process_job(config, store, job, identifier)
        except Exception as error:
            private_diagnostic(config, "worker-import", error)
            state["worker_error"] = type(error).__name__
        finally:
            state["done"].set()


def _request_json(client, action, release_id, **params):
    start = perf_counter()
    response = client.get("/api/v1/" + action, params={"release_id": release_id, **params})
    response.raise_for_status()
    value = response.json()
    if value.get("release_id") != release_id:
        raise ValueError("Query changed pinned release")
    return value, {"elapsed_seconds": perf_counter() - start, "bytes": len(response.content), "pages": 1}


def _query_export_samples(client, release, artifacts, args):
    release_id = release["release_id"]
    manifest, _ = _request_json(client, "manifest", release_id)
    concept = next(row["iri"] for row in manifest["concepts"] if row.get("table") == "ponds")
    expected = expected_export(artifacts["generate_rdf"]["nt_path"], concept)
    expected_count = len([row for row in artifacts["build_batch"]["snapshot"]["nodes"] if row["table_name"] == "ponds"])
    if expected["subjects"] != expected_count:
        raise ValueError("Generated RDF has an unexpected benchmark subject count")
    initial, _ = _request_json(client, "instances", release_id, **{"class": concept, "limit": args.page_size})
    if not initial["items"]:
        raise ValueError("Published class contains no instances")
    resource = initial["items"][0]["iri"]
    output = {"release_id": release_id, "class_iri": concept, "expected_export": expected, "samples": []}
    actions = [("instances", args.query_repeats), ("resource", args.query_repeats),
               ("export_json", args.export_repeats), ("export_csv", args.format_repeats), ("export_rdf", args.format_repeats)]
    for action, count in actions:
        for index in range(count):
            sample = {"action": action, "index": index, "status": "failed", "release_id": release_id}
            started = perf_counter()
            try:
                if action.startswith("export_"):
                    result = complete_export(client, release_id, concept, action.removeprefix("export_"), args.page_size)
                    sample.update(result)
                    if any(result[key] != expected[key] for key in expected):
                        raise ValueError("Complete export differs from independently generated RDF")
                else:
                    params = {"class": concept} if action == "instances" else {"iri": resource}
                    value, result = _request_json(client, action, release_id, limit=args.page_size, **params)
                    if action == "instances" and len(value["items"]) != min(expected_count, args.page_size):
                        raise ValueError("Instance page has an unexpected size")
                    if action == "resource" and (value.get("iri") != resource or not value.get("outgoing")):
                        raise ValueError("Resource response is incomplete")
                sample.update(result, status="passed")
            except Exception as error:
                if isinstance(error, ExportFailure):
                    sample.update(error.measurement, cause_type=error.error_type)
                sample.update(error_type=type(error).__name__, elapsed_seconds=perf_counter() - started)
            output["samples"].append(sample)
    output["summary"] = {action: summarize_samples([sample for sample in output["samples"] if sample["action"] == action]) for action, _ in actions}
    return output


def _import_sample(client, config, timing, args, size, index):
    sample = {"relation_rows": size, "phase": "first_pass" if index == 0 else "warm_new_content", "index": index, "status": "failed"}
    payload, metadata = synthetic_package(size, str(uuid4()))
    sample.update(metadata)
    state = timing.begin(sample)
    started = perf_counter()
    try:
        response = client.post("/api/v1/batches", params={"filename": "synthetic-benchmark.zip"}, content=payload,
                               headers={"Authorization": "Bearer " + config.write_token, "Content-Type": "application/zip"})
        sample["http_202_seconds"] = perf_counter() - started
        sample["http_status"] = response.status_code
        response.raise_for_status()
        if response.status_code != 202:
            raise ValueError("Upload was not accepted as an asynchronous job")
        job = response.json()
        sample["job_id"] = job["job_id"]
        if not state["done"].wait(args.job_timeout):
            raise TimeoutError("Benchmark worker did not finish before the explicit deadline")
        if state.get("worker_error"):
            sample["worker_error_type"] = state["worker_error"]
            raise RuntimeError("Benchmark worker reported failure")
        release = state["release"]
        if (release["counts"]["instances"] != size + 1 or release["counts"]["relations"] != size or
                release["counts"]["resolved_relations"] != size):
            raise ValueError("Actual release size differs from synthetic input")
        if any(row["nature"] != "synthetic" for row in state["artifacts"]["build_batch"]["snapshot"]["nodes"]):
            raise ValueError("Benchmark node data nature is not synthetic")
        # Visibility read is outside measured pipeline durations.
        status = client.get("/api/v1/status")
        status.raise_for_status()
        if status.json()["release_id"] != release["release_id"]:
            raise ValueError("Published release was not active over HTTP")
        sample.update(status="passed", release_id=release["release_id"], counts=release["counts"],
                      generated_triples=state["artifacts"]["generate_rdf"]["triple_count"],
                      generated_rdf_bytes=state["artifacts"]["generate_rdf"]["nt_bytes"],
                      release_data_nature=release["data_nature"], node_data_nature="synthetic")
    except Exception as error:
        private_diagnostic(config, "import-sample", error)
        sample["error_type"] = type(error).__name__
    sample.update(timing.metrics(state, started))
    sample["elapsed_seconds"] = sample.get("upload_to_complete_seconds", perf_counter() - started)
    sample["stages"] = {name: [{key: value for key, value in row.items() if key not in ("start", "end")} for row in rows]
                         for name, rows in state["stages"].items()}
    return sample, state


def _import_summary(samples):
    output = {}
    for phase in ("first_pass", "warm_new_content"):
        rows = [row for row in samples if row["phase"] == phase]
        metrics = sorted({key for row in rows for key in row if key.endswith("_seconds")})
        output[phase] = {"complete": summarize_samples(rows), "metrics": {}}
        for metric in metrics:
            values = [{"status": row["status"] if metric in row else "failed", "elapsed_seconds": row.get(metric, 0)} for row in rows]
            output[phase]["metrics"][metric] = summarize_samples(values)
    return output


def run_benchmark(config, marker, args):
    reject_indirect_libpq_environment()
    from local_server.http import make_handler
    from local_server.lifecycle import NativeServices, atomic_json
    from local_server.store import Store
    report = {"contract": CONTRACT, "started_utc": datetime.now(timezone.utc).isoformat(), "status": "failed",
        "data_nature": "synthetic CSV/ZIP; real PostgreSQL and Fuseki; not CAD import performance",
        "environment": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
                        "background_load": args.background_note, "workers": 1},
        "method": {"clock": "time.perf_counter", "first_pass": "first import at each size; OS caches were not cleared",
            "warm": "new content and distinct release for every repeat; no import deduplication",
            "query_export_release": "last successful release per size, fixed for all requests",
            "queue": "submit_job return to claim_job return, includes claim SQL; negative overlap clamped to zero",
            "import_processing": "claim return through verified SQL and RDF readback; publication excluded",
            "publication": "build_navigation start through publish_release return, including file verification and registration",
            "atomic_activation": "complete publish_release SQL transaction including connect, locks, release status, state update and commit",
            "export": "complete public ponds class only, all pages; wall time includes HTTP, parsing, validation; http_seconds also supplied",
            "p95": "nearest rank; successful samples only, all failures counted; small N cannot establish capacity"},
        "settings": {"sizes": args.sizes, "warm_repeats": args.warm_repeats, "query_repeats": args.query_repeats,
                     "json_export_repeats": args.export_repeats, "csv_rdf_repeats": args.format_repeats, "page_size": args.page_size},
        "scenarios": [], "cleanup": {}}
    native, server, worker, http_thread = NativeServices(config), None, None, None
    stop = threading.Event()
    lock_path = config.data_dir / ".benchmark-run.lock"
    with lock_path.open("x", encoding="utf-8") as claim:
        claim.write(marker["deployment_id"])
    marker = {**marker, "phase": "running"}
    atomic_json(config.data_dir / MARKER, marker)
    try:
        native.start()
        _empty_database_identity(config)
        with httpx.Client(timeout=30, trust_env=False) as probe:
            rdf = probe.post(config.fuseki_url + "/query", data={"query": "ASK { { ?s ?p ?o } UNION { GRAPH ?g { ?s ?p ?o } } }"}, headers={"Accept": "application/sparql-results+json"})
            rdf.raise_for_status()
            if rdf.json().get("boolean") is not False:
                raise ValueError("Benchmark RDF dataset is not empty")
        Store(config, role="admin").ensure_schema()
        if Store(config).list_jobs() or Store(config).list_releases():
            raise ValueError("Benchmark control store is not empty")
        server = ThreadingHTTPServer((config.host, config.port), make_handler(config, Store(config)))
        http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        http_thread.start()
        with PipelineTiming() as timing:
            worker = threading.Thread(target=_worker_loop, args=(config, timing, stop), daemon=True)
            worker.start()
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{config.port}", timeout=args.http_timeout, trust_env=False) as client:
                    for size in args.sizes:
                        scenario = {"relation_rows": size, "imports": []}
                        report["scenarios"].append(scenario)
                        for index in range(args.warm_repeats + 1):
                            sample, state = _import_sample(client, config, timing, args, size, index)
                            scenario["imports"].append(sample)
                            atomic_json(args.output, report)
                            print(json.dumps({"phase": "import", "relation_rows": size, "index": index, "status": sample["status"]}), flush=True)
                            if sample["status"] != "passed":
                                scenario["unattempted_imports"] = args.warm_repeats - index
                                raise RuntimeError("Import failed; remaining work explicitly unattempted")
                        scenario["summary"] = _import_summary(scenario["imports"])
                        try:
                            scenario["reads"] = _query_export_samples(client, state["release"], state["artifacts"], args)
                        except Exception as error:
                            private_diagnostic(config, "query-export-setup", error)
                            scenario["reads"] = {"status": "failed", "error_type": type(error).__name__, "samples": []}
                        atomic_json(args.output, report)
                        print(json.dumps({"phase": "query-export", "relation_rows": size, "completed": True}), flush=True)
            finally:
                stop.set()
                if worker is not None:
                    worker.join(timeout=20)
        failed = any(sample["status"] != "passed" for scenario in report["scenarios"] for sample in scenario["imports"])
        failed |= any(scenario.get("reads", {}).get("status") == "failed" or any(sample["status"] != "passed" for sample in scenario.get("reads", {}).get("samples", [])) for scenario in report["scenarios"])
        report["status"] = "failed" if failed else "passed"
    except Exception as error:
        private_diagnostic(config, "benchmark", error)
        report["error_type"] = type(error).__name__
    finally:
        stop.set()
        if server is not None:
            server.shutdown()
            server.server_close()
        if http_thread is not None:
            http_thread.join(timeout=5)
        try:
            native.stop()
            report["cleanup"]["native_services"] = native.status()
        except Exception as error:
            private_diagnostic(config, "cleanup", error)
            report["cleanup"]["error_type"] = type(error).__name__
            report["status"] = "failed"
        if worker is not None:
            worker.join(timeout=20)
            report["cleanup"]["worker_stopped"] = not worker.is_alive()
            if worker.is_alive():
                report["status"] = "failed"
        for scenario in report["scenarios"]:
            scenario["summary"] = _import_summary(scenario["imports"])
        report["unattempted_sizes"] = args.sizes[len(report["scenarios"]):]
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(config.data_dir / MARKER, {**marker, "phase": "finished", "status": report["status"]})
        atomic_json(args.output, report)
        lock_path.unlink(missing_ok=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--data-dir", type=Path, help="new nonexistent child of ROOT/.runtime; provision then run")
    target.add_argument("--config", type=Path, help="unused target previously prepared by this script")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--pg-bin", type=Path)
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--fuseki-home", type=Path)
    parser.add_argument("--pg-port", type=int, default=26559)
    parser.add_argument("--fuseki-port", type=int, default=24159)
    parser.add_argument("--http-port", type=int, default=8894)
    parser.add_argument("--sizes", type=lambda value: [int(item) for item in value.split(",")], default=[100, 1000, 5000])
    parser.add_argument("--warm-repeats", type=int, default=3)
    parser.add_argument("--query-repeats", type=int, default=20)
    parser.add_argument("--export-repeats", type=int, default=20)
    parser.add_argument("--format-repeats", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--job-timeout", type=int, default=1800)
    parser.add_argument("--http-timeout", type=int, default=120)
    parser.add_argument("--background-note", default="Existing formal services may remain active; no concurrent native regression permitted")
    parser.add_argument("--output", type=Path, help="sanitized result JSON, defaults to DATA/benchmark-results.json")
    args = parser.parse_args(argv)
    try:
        reject_indirect_libpq_environment()
        if (not args.sizes or len(set(args.sizes)) != len(args.sizes) or any(size < 1 for size in args.sizes) or
                args.warm_repeats < 0 or min(args.query_repeats, args.export_repeats, args.format_repeats, args.page_size, args.job_timeout, args.http_timeout) < 1):
            raise ValueError("Counts and timeouts must be positive; warm repeats can be zero")
        if args.prepare_only and args.config:
            raise ValueError("Prepare-only requires a fresh data directory")
        if args.data_dir:
            if any(value is None for value in (args.pg_bin, args.java_home, args.fuseki_home)):
                raise ValueError("Provisioning requires explicit PostgreSQL, Java and Fuseki tool paths")
            args.config = prepare_target(args)
        config, marker = load_target(args.config)
        if args.page_size > config.limits["max_page_size"]:
            raise ValueError("Page size exceeds configured service limit")
        if args.prepare_only:
            print(json.dumps({"status": "prepared", "config": str(args.config), "marker": MARKER}), flush=True)
            return 0
        args.output = (args.output or config.data_dir / "benchmark-results.json").resolve()
        report = run_benchmark(config, marker, args)
        print(json.dumps({"status": report["status"], "output": str(args.output)}), flush=True)
        return 0 if report["status"] == "passed" else 1
    except Exception as error:
        # No arbitrary exception strings: libpq, HTTP and path errors may
        # otherwise reveal private credentials or runtime locations.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
