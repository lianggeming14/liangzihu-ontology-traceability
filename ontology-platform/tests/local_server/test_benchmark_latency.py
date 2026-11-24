"""Benchmark must reject unsafe targets and never hide failed/incomplete samples."""
import importlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def bench():
    return importlib.import_module("scripts.bench_local_server")


@pytest.mark.parametrize("port", [8792, 25459, 23059, 25449, 23049])
def test_fresh_run_rejects_protected_ports_before_creating_files(tmp_path, port):
    target = tmp_path / ".runtime" / "benchmark-new"
    with pytest.raises(ValueError):
        bench().validate_new_run(tmp_path, target, (port, 25529, 23129))
    assert not target.exists()


def test_fresh_run_rejects_used_directory_and_external_path(tmp_path):
    target = tmp_path / ".runtime" / "benchmark-used"
    target.mkdir(parents=True)
    (target / "deployment.json").write_text("{}")
    with pytest.raises(ValueError):
        bench().validate_new_run(tmp_path, target, (8899, 25529, 23129))
    with pytest.raises(ValueError):
        bench().validate_new_run(tmp_path, tmp_path / "outside-runtime", (8899, 25529, 23129))


def target_config(tmp_path):
    data = tmp_path / ".runtime" / "benchmark-new"
    return SimpleNamespace(root=tmp_path, data_dir=data, config_path=data / "config.json", host="127.0.0.1", port=8899,
        sql={role + "_dsn": "host=127.0.0.1 port=25529 dbname=lzo_gis user=test" for role in ("admin", "api", "worker")},
        fuseki_url="http://127.0.0.1:23129/fish_l1", runtime={"managed_postgres": True, "managed_fuseki": True,
            "pg_data_dir": "postgres/data", "fuseki_state_dir": "fuseki", "pg_port": 25529, "fuseki_port": 23129})


def test_loaded_config_rejects_mixed_roles_remote_rdf_and_data_escape(tmp_path):
    config = target_config(tmp_path)
    bench().validate_config_targets(config)
    for changed in (
        {"sql": {**config.sql, "worker_dsn": "host=127.0.0.1 port=25459 dbname=lzo_gis user=test"}},
        {"sql": {**config.sql, "api_dsn": "host=127.0.0.1 port=25529 dbname=other user=test"}},
        {"fuseki_url": "http://example.com:23129/fish_l1"},
        {"runtime": {**config.runtime, "pg_data_dir": "../../formal-db"}},
    ):
        bad = SimpleNamespace(**{**vars(config), **changed})
        with pytest.raises(ValueError):
            bench().validate_config_targets(bad)


def test_readonly_database_identity_mismatch_refuses_schema_init(tmp_path):
    config = target_config(tmp_path)
    with pytest.raises(ValueError):
        bench().validate_database_identity(config, tmp_path / "formal-db", "lzo_gis", 25529)
    bench().validate_database_identity(config, config.data_dir / "postgres/data", "lzo_gis", 25529)


def test_statistics_preserve_failures_and_small_sample_size():
    result = bench().summarize_samples([
        {"status": "passed", "elapsed_seconds": 1}, {"status": "passed", "elapsed_seconds": 3},
        {"status": "failed", "elapsed_seconds": 90}])
    assert result["attempts"] == 3 and result["successes"] == 2 and result["failures"] == 1
    assert result["p50_seconds"] == 2 and result["p95_seconds"] == 3
    assert result["small_sample"] is True
    assert bench().summarize_samples([{"status": "failed", "elapsed_seconds": 1}])["p95_seconds"] is None


def test_json_export_consumes_all_pages_and_pins_release():
    def reply(request):
        assert request.url.params["release_id"] == "release-a"
        second = request.url.params.get("cursor") == "page-2"
        row = {"subject": "urn:s:2" if second else "urn:s:1", "predicate": "urn:p", "object": {"type": "literal", "value": "x"}}
        return httpx.Response(200, json={"release_id": "release-a", "items": [row], "next_cursor": None if second else "page-2"},
            headers={"X-Release-ID": "release-a", **({} if second else {"X-Next-Cursor": "page-2"})})
    with httpx.Client(transport=httpx.MockTransport(reply), base_url="http://127.0.0.1:8899") as client:
        result = bench().complete_export(client, "release-a", "urn:class", "json", 1)
    assert result["pages"] == 2 and result["triples"] == 2 and result["subjects"] == 2 and result["bytes"] > 100


@pytest.mark.parametrize("fault", ["release", "cycle", "http", "duplicate"])
def test_export_rejects_partial_or_inconsistent_results(fault):
    def reply(request):
        if fault == "http" and request.url.params.get("cursor"):
            return httpx.Response(503)
        row = {"subject": "urn:s", "predicate": "urn:p", "object": {"type": "literal", "value": "x"}}
        return httpx.Response(200, json={"release_id": "wrong" if fault == "release" else "release-a", "items": [row],
            "next_cursor": "next" if fault != "duplicate" or not request.url.params.get("cursor") else None},
            headers={"X-Release-ID": "release-a", "X-Next-Cursor": "next" if fault != "duplicate" or not request.url.params.get("cursor") else ""})
    with httpx.Client(transport=httpx.MockTransport(reply), base_url="http://127.0.0.1:8899") as client:
        with pytest.raises((ValueError, httpx.HTTPError)):
            bench().complete_export(client, "release-a", "urn:class", "json", 1)


def test_synthetic_packages_have_requested_relations_and_unique_content():
    first, meta = bench().synthetic_package(3, "first")
    second, _ = bench().synthetic_package(3, "second")
    assert first != second and meta["relation_rows"] == 3 and meta["source_rows"] == 4
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        ponds = archive.read("ponds.csv").decode()
        assert len(ponds.splitlines()) == 4
        assert all(line.endswith(",true") for line in ponds.splitlines()[1:])


@pytest.mark.parametrize("fmt", ["csv", "rdf"])
def test_text_exports_consume_pages_and_match_json_term_fingerprint(fmt):
    def reply(request):
        assert request.url.params["release_id"] == "release-a"
        second = request.url.params.get("cursor") == "page-2"
        subject = "urn:s:2" if second else "urn:s:1"
        if request.url.params["format"] == "csv":
            payload = "subject,predicate,value,type,datatype,language\n" + subject + ",urn:p,x,literal,,\n"
            kwargs = {"text": payload}
        elif request.url.params["format"] == "rdf":
            kwargs = {"text": f'<{subject}> <urn:p> "x" .\n'}
        else:
            kwargs = {"json": {"release_id": "release-a", "items": [{"subject": subject, "predicate": "urn:p", "object": {"type": "literal", "value": "x"}}], "next_cursor": None if second else "page-2"}}
        return httpx.Response(200, **kwargs, headers={"X-Release-ID": "release-a", **({} if second else {"X-Next-Cursor": "page-2"})})
    with httpx.Client(transport=httpx.MockTransport(reply), base_url="http://127.0.0.1:8899") as client:
        baseline = bench().complete_export(client, "release-a", "urn:class", "json", 1)
        result = bench().complete_export(client, "release-a", "urn:class", fmt, 1)
    assert result["pages"] == 2 and result["triples"] == 2 and result["subjects"] == 2
    assert result["termset_sha256"] == baseline["termset_sha256"]


def test_generated_synthetic_model_and_export_oracle_have_exact_requested_size(tmp_path):
    from local_server.importer import build_batch, load_mapping
    from local_server.rdf import generate_rdf
    from fish_rdf_sample import uri_factory
    payload, _ = bench().synthetic_package(3, "real-model")
    path = tmp_path / "input.zip"
    path.write_bytes(payload)
    batch = build_batch(path, tmp_path / "input", load_mapping(ROOT / "config/local-server-mapping.json"))
    assert len(batch["snapshot"]["relations"]) == 3
    assert len(batch["snapshot"]["nodes"]) == 4
    assert {node["nature"] for node in batch["snapshot"]["nodes"]} == {"synthetic"}
    generated = generate_rdf(batch, tmp_path / "rdf")
    expected = bench().expected_export(generated["nt_path"], str(uri_factory(batch["namespace"])("class", "ponds")))
    assert expected["subjects"] == 3
    assert expected["triples"] > 3 and expected["triples"] < generated["triple_count"]


def test_private_environment_ignores_inherited_values_and_restores_them(tmp_path, monkeypatch):
    from local_server.provision import SQL_ENV
    keys = [*SQL_ENV.values(), "LZO_LOCAL_WRITE_TOKEN"]
    private = tmp_path / "private.env"
    private.write_text("\n".join(key + "=new-benchmark-value" for key in keys))
    monkeypatch.setenv(keys[0], "inherited-formal-value")
    with bench()._private_environment(private):
        import os
        assert all(os.environ[key] == "new-benchmark-value" for key in keys)
    assert os.environ[keys[0]] == "inherited-formal-value"
    private.write_text(keys[0] + "=incomplete")
    with pytest.raises(ValueError):
        with bench()._private_environment(private):
            pytest.fail("Missing private values must not fall back to inherited credentials")


def test_missing_pipeline_stage_remains_a_failure_in_summary():
    samples = [{"phase": "warm_new_content", "status": "passed", "elapsed_seconds": 3, "publication_seconds": 1},
               {"phase": "warm_new_content", "status": "failed", "elapsed_seconds": 5}]
    summary = bench()._import_summary(samples)["warm_new_content"]
    assert summary["complete"]["attempts"] == 2 and summary["complete"]["failures"] == 1
    assert summary["metrics"]["publication_seconds"]["attempts"] == 2
    assert summary["metrics"]["publication_seconds"]["failures"] == 1


def test_claim_started_before_submission_is_recorded_for_the_claimed_sample():
    timing = bench().PipelineTiming()
    class Queue:
        def claim_job(self):
            timing.begin({"index": 0})
            return {"job_id": "claimed"}
    try:
        timing._wrap(Queue, "claim_job")
        assert Queue().claim_job()["job_id"] == "claimed"
        assert len(timing.current["stages"]["claim_job"]) == 1
    finally:
        timing.__exit__()


def test_failed_second_export_page_preserves_completed_page_evidence():
    def reply(request):
        if request.url.params.get("cursor"):
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={"release_id": "release-a", "items": [{"subject": "urn:s", "predicate": "urn:p", "object": {"type": "literal", "value": "x"}}], "next_cursor": "page2"},
                              headers={"X-Release-ID": "release-a", "X-Next-Cursor": "page2"})
    with httpx.Client(transport=httpx.MockTransport(reply), base_url="http://127.0.0.1:8899") as client:
        with pytest.raises(ValueError) as error:
            bench().complete_export(client, "release-a", "urn:class", "json", 1)
    assert error.value.measurement["pages"] == 1
    assert error.value.measurement["triples"] == 1
    assert error.value.measurement["bytes"] > 0


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
@pytest.mark.parametrize("entry", ["prepare", "load", "run"])
def test_indirect_libpq_environment_is_rejected_before_provision_or_target_access(tmp_path, monkeypatch, key, entry):
    from local_server import provision
    monkeypatch.setenv(key, "inherited-indirect-target")
    def forbidden(*args, **kwargs):
        pytest.fail("Inherited libpq redirection must be rejected before provisioning")
    monkeypatch.setattr(provision, "provision_fresh", forbidden)
    args = SimpleNamespace(root=tmp_path, data_dir=tmp_path / ".runtime" / "fresh", http_port=8894,
                           pg_port=26559, fuseki_port=24159, pg_bin=tmp_path, java_home=tmp_path, fuseki_home=tmp_path)
    with pytest.raises(ValueError, match="libpq"):
        if entry == "prepare":
            bench().prepare_target(args)
        elif entry == "load":
            bench().load_target(tmp_path / "nonexistent" / "config.json")
        else:
            bench().run_benchmark(SimpleNamespace(), {}, args)
    assert not args.data_dir.exists()


def test_complete_but_wrong_export_retains_page_byte_and_triple_measurements(monkeypatch):
    def reply(request):
        action = request.url.path.rsplit("/", 1)[-1]
        body = {"release_id": "release-a"}
        if action == "manifest":
            return httpx.Response(200, json={**body, "concepts": [{"iri": "urn:class", "table": "ponds"}]})
        if action == "instances":
            return httpx.Response(200, json={**body, "items": [{"iri": "urn:s"}]})
        if action == "resource":
            return httpx.Response(200, json={**body, "iri": "urn:s", "outgoing": [{"predicate": "urn:p"}]})
        fmt = request.url.params["format"]
        if fmt == "json":
            kwargs = {"json": {**body, "items": [{"subject": "urn:s", "predicate": "urn:p", "object": {"type": "literal", "value": "x"}}], "next_cursor": None}}
        elif fmt == "csv":
            kwargs = {"text": "subject,predicate,value,type,datatype,language\nurn:s,urn:p,x,literal,,\n"}
        else:
            kwargs = {"text": '<urn:s> <urn:p> "x" .\n'}
        return httpx.Response(200, **kwargs, headers={"X-Release-ID": "release-a"})
    monkeypatch.setattr(bench(), "expected_export", lambda *args: {"subjects": 1, "triples": 2, "termset_sha256": "different"})
    artifacts = {"generate_rdf": {"nt_path": "unused"}, "build_batch": {"snapshot": {"nodes": [{"table_name": "ponds"}]}}}
    args = SimpleNamespace(page_size=1, query_repeats=1, export_repeats=1, format_repeats=1)
    with httpx.Client(transport=httpx.MockTransport(reply), base_url="http://127.0.0.1:8894") as client:
        result = bench()._query_export_samples(client, {"release_id": "release-a"}, artifacts, args)
    samples = [sample for sample in result["samples"] if sample["action"].startswith("export_")]
    assert len(samples) == 3
    for sample in samples:
        assert sample["status"] == "failed"
        assert sample["pages"] == 1 and sample["triples"] == 1 and sample["bytes"] > 0


def test_failure_traceback_is_private_and_never_printed(tmp_path, capsys):
    secret_local_variable = "synthetic-secret-local-must-not-be-captured"
    try:
        raise ValueError("synthetic diagnostic failure")
    except ValueError as error:
        bench().private_diagnostic(SimpleNamespace(data_dir=tmp_path), "worker", error)
    text = (tmp_path / "benchmark-diagnostics.log").read_text(encoding="utf-8")
    assert "synthetic diagnostic failure" in text and "test_failure_traceback_is_private" in text
    assert secret_local_variable not in text
    assert capsys.readouterr().out == ""


def test_rdf11_string_identity_is_equal_but_numeric_lexical_forms_stay_distinct():
    from rdflib import Literal
    from rdflib.namespace import XSD
    key = lambda obj: bench()._triple_key("urn:s", "urn:p", obj)
    assert key(Literal("same")) == key({"type": "literal", "value": "same", "datatype": str(XSD.string)})
    assert key(Literal("01", datatype=XSD.integer, normalize=False)) != key({"type": "literal", "value": "1", "datatype": str(XSD.integer)})
    assert key({"type": "literal", "value": "01", "datatype": str(XSD.integer)}) != key({"type": "literal", "value": "1", "datatype": str(XSD.integer)})
    assert key(Literal("123456789012345678.123456789", datatype=XSD.decimal, normalize=False)) != key(Literal("123456789012345678.123456788", datatype=XSD.decimal, normalize=False))
    assert key(Literal("same", lang="en")) != key(Literal("same", lang="fr"))
    assert key({"type": "uri", "value": "urn:o"}) != key(Literal("urn:o"))


@pytest.mark.parametrize("fmt", ["json", "csv", "rdf"])
def test_real_rdf_oracle_and_exports_preserve_terms_across_rdf11_string_spelling(tmp_path, fmt):
    import rdflib
    from rdflib.namespace import RDF, XSD
    path = tmp_path / "source.nt"
    path.write_text(f'<urn:s> <{RDF.type}> <urn:class> .\n<urn:s> <urn:label> "same" .\n<urn:s> <urn:amount> "01"^^<{XSD.integer}> .\n', encoding="utf-8")
    normalizing_before = rdflib.NORMALIZE_LITERALS
    expected = bench().expected_export(path, "urn:class")
    assert rdflib.NORMALIZE_LITERALS is normalizing_before
    def reply(request):
        assert request.url.params["release_id"] == "release-a"
        if fmt == "json":
            kwargs = {"json": {"release_id": "release-a", "next_cursor": None, "items": [
                {"subject": "urn:s", "predicate": str(RDF.type), "object": {"type": "uri", "value": "urn:class"}},
                {"subject": "urn:s", "predicate": "urn:label", "object": {"type": "literal", "value": "same", "datatype": str(XSD.string)}},
                {"subject": "urn:s", "predicate": "urn:amount", "object": {"type": "literal", "value": "01", "datatype": str(XSD.integer)}}]}}
        elif fmt == "csv":
            kwargs = {"text": f'subject,predicate,value,type,datatype,language\nurn:s,{RDF.type},urn:class,uri,,\nurn:s,urn:label,same,literal,{XSD.string},\nurn:s,urn:amount,01,literal,{XSD.integer},\n'}
        else:
            kwargs = {"text": f'<urn:s> <{RDF.type}> <urn:class> .\n<urn:s> <urn:label> "same"^^<{XSD.string}> .\n<urn:s> <urn:amount> "01"^^<{XSD.integer}> .\n'}
        return httpx.Response(200, **kwargs, headers={"X-Release-ID": "release-a"})
    with httpx.Client(transport=httpx.MockTransport(reply), base_url="http://127.0.0.1:8894") as client:
        actual = bench().complete_export(client, "release-a", "urn:class", fmt, 100)
    assert all(actual[key] == expected[key] for key in expected)
    assert rdflib.NORMALIZE_LITERALS is normalizing_before
    path.write_text(path.read_text(encoding="utf-8").replace('"01"^^', '"1"^^'), encoding="utf-8")
    changed = bench().expected_export(path, "urn:class")
    assert changed["termset_sha256"] != actual["termset_sha256"]
