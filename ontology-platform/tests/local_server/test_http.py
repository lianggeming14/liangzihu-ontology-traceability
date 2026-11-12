"""Run the actual HTTP handler with isolated files and a small in-memory store."""
from contextlib import contextmanager
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import httpx
import pytest

from local_server.http import make_handler
from local_server.query import QueryService


class MemoryStore:
    def __init__(self, release):
        self.release, self.jobs = release, []
        self.releases = [release]

    def active_release(self): return self.release
    def get_release(self, value): return next((row for row in self.releases if row["release_id"] == value), None)
    def list_releases(self, limit=100, offset=0): return self.releases[offset:offset+limit]
    def list_jobs(self, limit=100, offset=0): return self.jobs[offset:offset+limit]
    def get_job(self, value): return next((job for job in self.jobs if job["job_id"] == value), None)
    def submit_job(self, path, digest, mapping, **kwargs):
        for row in self.jobs:
            if (row["source_sha256"], row["mapping_sha256"]) == (digest, mapping): return row
        row = {"job_id": str(len(self.jobs)+1), "source_sha256": digest, "mapping_sha256": mapping, "status": "queued", "source_path": str(path), **kwargs}
        self.jobs.append(row)
        return row


@pytest.fixture
def setup(tmp_path):
    review = tmp_path / "review"
    (review / "data").mkdir(parents=True)
    (review / "index.html").write_text("本体浏览", encoding="utf-8")
    (review / "private.env").write_text("PRIVATE=secret", encoding="utf-8")
    manifest = {"namespace": "urn:test:", "counts": {}, "concepts": []}
    manifest_path = review / "data" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"version": "test", "definitions": {"tables": {}}}), encoding="utf-8")
    data = tmp_path / "private"
    data.mkdir()
    config = SimpleNamespace(root=tmp_path, data_dir=data, review_dir=review, mapping_file=mapping,
        write_token="synthetic-private-token", allowed_hosts=(), host="127.0.0.1", port=0, schema_version="1",
        fuseki_url="http://127.0.0.1:23059/fish_l1", limits={"upload_bytes": 1024, "page_size": 10, "max_page_size": 100, "query_timeout_seconds": 1, "min_free_disk_bytes": 1})
    release = {"release_id": "r1", "status":"published", "path_base": "review", "legacy_snapshot": True, "manifest_path": "data/manifest.json", "navigation_dir": ".", "namespace": "urn:test:", "rdf_graph": "urn:test:graph", "source_path": "SECRET_PRIVATE_PATH", "sql_schema": "safe_schema"}
    return config, MemoryStore(release)


@contextmanager
def serving(config, store):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(config, store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as client: yield client
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_status_and_static_files_are_public_but_private_files_are_not(setup):
    config, store = setup
    with serving(config, store) as client:
        result = client.get("/api/v1/status")
        assert result.status_code == 200
        assert "SECRET_PRIVATE_PATH" not in result.text
        assert client.get("/").status_code == 200
        assert "本体浏览" in client.get("/ontology/").text
        for path in ("/ontology/private.env", "/ontology/../private.env", "/ontology/%2e%2e/private.env", "/.git/config"):
            assert client.get(path).status_code == 404
        assert "Access-Control-Allow-Origin" not in result.headers


def test_upload_requires_token_and_same_host_origin(setup):
    config, store = setup
    with serving(config, store) as client:
        headers = {"Authorization": "Bearer synthetic-private-token"}
        assert client.post("/api/v1/batches?filename=ponds.csv", content=b"id,name\n1,p\n").status_code == 401
        assert client.post("/api/v1/batches?filename=ponds.csv", content=b"id\n1", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/v1/batches?filename=ponds.csv", content=b"id\n1", headers={**headers, "Host": "evil.example"}).status_code == 403
        response = client.post("/api/v1/batches?filename=ponds.csv", content=b"id,name\n1,p\n", headers=headers)
        assert response.status_code == 202
        assert "source_path" not in response.json()
        again = client.post("/api/v1/batches?filename=ponds.csv", content=b"id,name\n1,p\n", headers=headers)
        assert again.json()["job_id"] == response.json()["job_id"]
        assert Path(store.jobs[0]["source_path"]).name == "ponds.csv"


def test_upload_rejects_traversal_oversize_and_preserves_csv_table_identity(setup):
    config, store = setup
    with serving(config, store) as client:
        headers = {"Authorization": "Bearer synthetic-private-token"}
        for name in ("../x.csv", "C:\\x.csv", "x.txt", "a%2fb.csv"):
            assert client.post("/api/v1/batches?filename="+name, content=b"id\n1", headers=headers).status_code == 400
        assert client.post("/api/v1/batches?filename=x.csv", content=b"x"*1025, headers=headers).status_code == 413
        one = client.post("/api/v1/batches?filename=ponds.csv", content=b"id\n1", headers=headers).json()
        two = client.post("/api/v1/batches?filename=fish.csv", content=b"id\n1", headers=headers).json()
        assert one["job_id"] != two["job_id"]


def test_backend_errors_are_sanitized(setup):
    config, store = setup
    def unavailable(): raise RuntimeError("postgresql://admin:PASSWORD@host/db")
    store.active_release = unavailable
    with serving(config, store) as client:
        response = client.get("/api/v1/status")
        assert response.status_code == 503
        error = response.json()["error"]
        assert set(error) == {"code", "message", "request_id", "retryable"}
        assert "PASSWORD" not in response.text


def test_missing_required_query_parameter_is_a_client_error(setup):
    config, store = setup
    with serving(config, store) as client:
        assert client.get("/api/v1/instances").status_code == 400


def test_legacy_browser_pins_release_and_adapts_new_navigation_contract(setup):
    config, store = setup
    manifest = config.data_dir/"public"/"manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"contract":"local-server-navigation/1","concepts":[],"namespace":"urn:test:"}),encoding="utf8")
    store.release.update(path_base="data",legacy_snapshot=False,navigation_dir="public",manifest_path="public/manifest.json")
    with serving(config,store) as client:
        page = client.get("/ontology/")
        assert 'name="local-release-id" content="r1"' in page.text
        value = client.get("/ontology/data/manifest.json?release_id=r1").json()
        assert value["contract"] == "fish-rdf-review/1"
        assert value["source_contract"] == "local-server-navigation/1"
        assert value["release_id"] == "r1"


def test_release_history_lists_published_versions_without_exposing_staging(setup):
    config, store = setup
    store.releases = [{**store.release,"release_id":"r0","status":"published"},
                      {**store.release,"release_id":"r1","status":"published"},
                      {**store.release,"release_id":"staging","status":"ready"}]
    with serving(config,store) as client:
        value=client.get("/api/v1/releases").json()
        assert [row["release_id"] for row in value["items"]] == ["r0","r1"]
        assert client.get("/api/v1/releases/staging").status_code == 404
        assert client.get("/api/v1/manifest?release_id=staging").status_code == 404


def test_zip_filename_is_not_a_logical_table_and_can_include_hyphens(setup):
    config, store = setup
    with serving(config,store) as client:
        headers = {"Authorization":"Bearer synthetic-private-token"}
        first = client.post("/api/v1/batches?filename=source-2026.ZIP",content=b"synthetic-archive-bytes",headers=headers)
        second = client.post("/api/v1/batches?filename=another-name.zip",content=b"synthetic-archive-bytes",headers=headers)
        assert first.status_code == second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]


def test_rejected_post_bodies_still_receive_structured_error_responses(setup):
    config, store = setup
    with serving(config,store) as client:
        for _ in range(20):
            response=client.post("/api/v1/batches?filename=ponds.csv",content=b"rejected-body"*100)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert store.jobs == []


def test_rdf_export_preserves_literal_lexical_forms_datatypes_and_language(setup,monkeypatch):
    config,store=setup
    manifest_path=config.review_dir/"data"/"manifest.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf8"))
    manifest["concepts"]=[{"iri":"urn:test:class:ponds"}]
    manifest_path.write_text(json.dumps(manifest),encoding="utf8")
    values=[{"type":"literal","value":"2024-06-01T12:34:56.123456789Z","datatype":"http://www.w3.org/2001/XMLSchema#dateTime"},
            {"type":"literal","value":"0001.2300","datatype":"http://www.w3.org/2001/XMLSchema#decimal"},
            {"type":"literal","value":"Bonjour","xml:lang":"fr"}]
    rows=[{"subject":{"value":"urn:test:instance:one"},"predicate":{"value":"urn:test:property:p"+str(index)},"object":value} for index,value in enumerate(values)]
    monkeypatch.setattr(QueryService,"query",lambda self,_:rows)
    with serving(config,store) as client:
        response=client.get("/api/v1/export",params={"class":"urn:test:class:ponds","format":"rdf"})
        assert response.status_code==200
        assert '"2024-06-01T12:34:56.123456789Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>' in response.text
        assert '"0001.2300"^^<http://www.w3.org/2001/XMLSchema#decimal>' in response.text
        assert '"Bonjour"@fr' in response.text
