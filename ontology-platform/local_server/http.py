"""Loopback control console and bounded versioned read API."""
from __future__ import annotations

import csv
import hashlib
import hmac
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
from pathlib import Path
import re
import shutil
import time
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from .config import contained_path
from .importer import input_mapping_hash, load_mapping
from .query import QueryError, QueryService, public_release, release_path
from .store import Store

WEB = Path(__file__).parent / "web"


def public_job(job):
    keys = ("job_id", "status", "stage", "created_at", "updated_at", "attempts", "progress", "error", "result")
    return {key: job[key] for key in keys if key in job}


def make_handler(config, store=None):
    store = store or Store(config, role="api")

    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalOntology/1"
        sys_version = ""
        protocol_version = "HTTP/1.0"

        def log_message(self, *_):
            # Never record URL/query/body/token/DSN. Process diagnostics are
            # captured by the supervisor in bounded rotating files.
            pass

        def response(self, data, status=200, content_type="application/json; charset=utf-8", headers=None):
            if status >= 400 and self.command in ("POST","PUT","PATCH"):
                self.discard_body()
            if isinstance(data, (dict, list)):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            elif isinstance(data, str):
                data = data.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def discard_body(self):
            # Closing a Windows TCP socket with unread upload bytes can reset
            # the connection before the client receives its 401/403/413 DTO.
            # Drain only bounded declared bytes, with a total time budget;
            # rejected content is neither retained, interpreted nor logged.
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 20:
                return
            remaining = getattr(self,"_unread_body",int(lengths[0]))
            remaining = min(remaining,config.limits["upload_bytes"]+65536)
            deadline = time.monotonic()+2
            try:
                self.connection.settimeout(.5)
                while remaining and time.monotonic() < deadline:
                    block = self.rfile.read(min(65536,remaining))
                    if not block:
                        break
                    remaining -= len(block)
            except OSError:
                pass
            self._unread_body = remaining

        def error(self, code, status, message, retryable=False):
            return self.response({"error": {"code": code, "message": message, "request_id": self.request_id, "retryable": bool(retryable)}}, status)

        def boundary(self, write=False):
            self.request_id = str(uuid4())
            if len(self.path) > 16384:
                self.error("INVALID_REQUEST", 400, "请求地址超出限制")
                return False
            hosts = config.allowed_hosts or (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}", f"[::1]:{self.server.server_port}")
            raw = self.headers.get_all("Host", [])
            if len(raw) != 1 or raw[0].lower() not in {host.lower() for host in hosts}:
                self.error("HOST_REJECTED", 403, "请求主机不在本机允许列表")
                return False
            origins = self.headers.get_all("Origin", [])
            if origins and (len(origins) != 1 or origins[0] != "http://" + raw[0]):
                self.error("ORIGIN_REJECTED", 403, "仅接受同源本机请求")
                return False
            if write:
                authorizations = self.headers.get_all("Authorization", [])
                expected = "Bearer " + config.write_token
                if not config.write_token or len(authorizations) != 1 or not hmac.compare_digest(authorizations[0].encode(), expected.encode()):
                    self.error("UNAUTHORIZED", 401, "请输入本机写入凭据")
                    return False
            return True

        def params(self, query):
            values = parse_qs(query, keep_blank_values=True)
            if any(len(value) != 1 for value in values.values()):
                raise QueryError("Repeated query parameters")
            return {key: value[0] for key, value in values.items()}

        def active(self, params):
            release_id = params.get("release_id")
            release = store.get_release(release_id) if release_id else store.active_release()
            if release is None or release.get("status") != "published":
                raise LookupError("No published release")
            return release

        def do_GET(self):
            if not self.boundary():
                return
            try:
                request = urlsplit(self.path)
                params = self.params(request.query)
                route = request.path
                if route in ("/health", "/api/v1/health"):
                    return self.response({"status": "alive", "service": "local-ontology/1"})
                if route in ("/api/v1/status", "/api/v1/ready", "/ready"):
                    release = store.active_release()
                    value = {"status": "ready" if release else "awaiting_release", "release_id": release["release_id"] if release else None,
                             "active_release": public_release(release), "jobs": [public_job(job) for job in store.list_jobs(limit=20)],
                             "write_enabled": bool(config.write_token), "ontology_url": "/ontology/", "data_nature": release.get("data_nature", "imported_unverified") if release else None}
                    if route in ("/api/v1/ready", "/ready") and release:
                        value["rdf"] = QueryService(config, release).status()
                        if not value["rdf"]["available"]:
                            value["status"] = "degraded"
                            return self.response(value, 503)
                    return self.response(value)
                if route == "/api/v1/jobs":
                    return self.response({"items": [public_job(job) for job in store.list_jobs(limit=min(100, int(params.get("limit", 20))))]})
                if route.startswith("/api/v1/jobs/"):
                    job = store.get_job(route.rsplit("/", 1)[1])
                    return self.response(public_job(job)) if job else self.error("NOT_FOUND", 404, "未找到任务")
                if route == "/api/v1/releases":
                    limit, offset = int(params.get("limit",min(20,config.limits["max_page_size"]))), int(params.get("offset",0))
                    if not 1 <= limit <= min(1000,config.limits["max_page_size"]) or offset < 0:
                        raise QueryError("Invalid release page")
                    rows = store.list_releases(limit=limit,offset=offset)
                    active = store.active_release()
                    return self.response({"release_id": active["release_id"] if active else None,
                        "items": [public_release(row) for row in rows if row.get("status") == "published"],
                        "limit":limit,"offset":offset,"next_offset":offset+limit if len(rows)==limit else None})
                if route.startswith("/api/v1/releases/"):
                    release = store.get_release(route.rsplit("/", 1)[1])
                    return self.response(public_release(release)) if release and release.get("status") == "published" else self.error("NOT_FOUND", 404, "未找到发布版本")
                if route.startswith(("/api/v1/", "/api/ontology/")):
                    release = self.active(params)
                    reader = QueryService(config, release)
                    action = route.rsplit("/", 1)[1]
                    if action == "status":
                        return self.response(reader.status())
                    if action in ("manifest", "hierarchy"):
                        return self.response({**reader.manifest, "release_id": release["release_id"]})
                    if action == "children":
                        return self.response(reader.children(params["parent"]))
                    if action == "instances":
                        return self.response(reader.instances(params["class"], limit=params.get("limit"), cursor=params.get("cursor"), offset=params.get("offset", 0)))
                    if action in ("resource", "properties", "relations"):
                        return self.response(reader.resource(params["iri"], limit=params.get("limit"), cursor=params.get("cursor"), incoming_cursor=params.get("incoming_cursor"), outgoing_offset=params.get("outgoing_offset", 0), incoming_offset=params.get("incoming_offset", 0)))
                    if action in ("maps", "map"):
                        return self.response(reader.maps())
                    if action == "network":
                        return self.response(reader.network())
                    if action == "network-relations":
                        return self.response(reader.network_relations(params["source"], params["predicate"], params["target"], limit=params.get("limit"), cursor=params.get("cursor")))
                    if action == "export":
                        value = reader.export(params["class"], limit=params.get("limit"), cursor=params.get("cursor"))
                        fmt = params.get("format", "json")
                        headers = {"X-Release-ID": reader.release_id}
                        if value["next_cursor"]:
                            headers["X-Next-Cursor"] = value["next_cursor"]
                        if fmt == "json":
                            return self.response(value, headers=headers)
                        if fmt == "csv":
                            output = io.StringIO(newline="")
                            writer = csv.writer(output)
                            writer.writerow(("subject", "predicate", "value", "type", "datatype", "language"))
                            for row in value["items"]:
                                obj = row["object"]
                                cells = (row["subject"], row["predicate"], obj["value"], obj.get("type"), obj.get("datatype"), obj.get("xml:lang"))
                                # Spreadsheet readers must not execute data cells.
                                writer.writerow("'" + cell if isinstance(cell, str) and cell.startswith(("=", "+", "-", "@", "\t", "\r")) else cell for cell in cells)
                            return self.response(output.getvalue(), content_type="text/csv; charset=utf-8", headers=headers)
                        if fmt == "rdf":
                            from rdflib import URIRef, Literal, BNode
                            lines = []
                            for row in value["items"]:
                                obj = row["object"]
                                term = URIRef(obj["value"]) if obj["type"] == "uri" else BNode(obj["value"]) if obj["type"] == "bnode" else Literal(obj["value"], lang=obj.get("xml:lang"), datatype=URIRef(obj["datatype"]) if obj.get("datatype") else None, normalize=False)
                                lines.append(URIRef(row["subject"]).n3()+" "+URIRef(row["predicate"]).n3()+" "+term.n3()+" .\n")
                            return self.response("".join(lines), content_type="text/turtle; charset=utf-8", headers=headers)
                        raise QueryError("Export format must be json, csv or rdf")
                    return self.error("NOT_FOUND", 404, "未找到接口")
                return self.static(route, params)
            except (QueryError, ValueError, KeyError, TypeError):
                return self.error("INVALID_REQUEST", 400, "请求参数无效；请检查发布版本、标识符和分页参数")
            except LookupError:
                return self.error("NO_RELEASE", 404, "尚无可用的发布版本")
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                return self.error("SERVICE_UNAVAILABLE", 503, "服务暂不可用；请查看本机状态和任务阶段", True)

        def static(self, route, params):
            if route in ("/", "/index.html", "/console.js", "/console.css", "/ontology-bridge.js"):
                filename = "index.html" if route in ("/", "/index.html") else route[1:]
                path = WEB / filename
            elif route.startswith("/ontology/"):
                relative = unquote(route[len("/ontology/"):]) or "index.html"
                if "\\" in relative or any(part in ("", ".", "..") or part.startswith(".") for part in relative.split("/")):
                    return self.error("NOT_FOUND", 404, "未找到文件")
                ui = {"index.html", "assets.js", "assets.css", "model.mjs", "spatial-map.mjs", "ontology-sphere.mjs", "sphere-math.mjs"}
                data = bool(re.fullmatch(r"data/(?:manifest\.json|map-features\.json|legacy-map-features\.json|ontology-network\.json|(?:classes|details|relations)/[A-Za-z0-9_./-]+\.json(?:\.gz)?)", relative))
                if relative in ui:
                    path = contained_path(config.review_dir, relative)
                    if relative == "index.html":
                        release = self.active(params)
                        bridge = '<meta name="local-release-id" content="'+escape(str(release["release_id"]),quote=True)+'"><script src="/ontology-bridge.js"></script>'
                        markup = path.read_text(encoding="utf-8")
                        markup = markup.replace("<head>", "<head>"+bridge, 1) if "<head>" in markup else bridge+markup
                        return self.response(markup,content_type="text/html; charset=utf-8")
                elif data:
                    release = self.active(params)
                    if relative == "data/ontology-network.json":
                        # The static view shares the API's whitelist, integrity
                        # checks and explicit historical-unavailable response.
                        return self.response(QueryService(config, release).network())
                    nav = release_path(config, release, release["navigation_dir"])
                    # The legacy page is kept as an explicit historical view.
                    # New batches have their own manifest/shards and use the
                    # console's versioned API browser.
                    path = contained_path(nav, relative)
                    if relative == "data/manifest.json" and not path.is_file():
                        path = release_path(config, release, release["manifest_path"])
                    files = release.get("navigation", {}).get("files", {})
                    if files and relative not in files and relative != "data/manifest.json":
                        return self.error("NOT_FOUND", 404, "未找到发布文件")
                    if relative == "data/manifest.json":
                        manifest = json.loads(path.read_text(encoding="utf-8"))
                        # Contract adapter for the existing, unmodified browser.
                        # The versioned API keeps the source manifest contract.
                        return self.response({**manifest, "contract": "fish-rdf-review/1", "source_contract": manifest.get("contract"), "release_id": release["release_id"]})
                else:
                    return self.error("NOT_FOUND", 404, "未找到文件")
            else:
                return self.error("NOT_FOUND", 404, "未找到文件")
            if not path.is_file() or path.stat().st_size > 64*1024*1024:
                return self.error("NOT_FOUND", 404, "未找到文件")
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            headers = {}
            if path.suffix == ".gz":
                # Legacy JS calls DecompressionStream explicitly.
                content_type = "application/gzip"
            return self.response(path.read_bytes(), content_type=content_type, headers=headers)

        def do_POST(self):
            if not self.boundary(write=True):
                return
            try:
                request = urlsplit(self.path)
                if request.path != "/api/v1/batches":
                    return self.error("NOT_FOUND", 404, "未找到写入接口")
                params = self.params(request.query)
                if set(params) != {"filename"}:
                    raise QueryError("One upload filename is required")
                filename = params["filename"]
                suffix = Path(filename).suffix.lower()
                stem = Path(filename).stem
                reserved = {"CON","PRN","AUX","NUL",*("COM"+str(number) for number in range(1,10)),*("LPT"+str(number) for number in range(1,10))}
                if (len(filename.encode("utf-8")) > 200 or filename.split(".",1)[0].upper() in reserved
                    or any(char in filename for char in '/\\\x00:*?"<>|')
                    or (suffix == ".csv" and not re.fullmatch(r"[a-z][a-z0-9_]{0,49}",stem))
                    or (suffix == ".zip" and not re.fullmatch(r"[\w-][\w .-]{0,150}",stem))
                    or suffix not in (".csv",".zip")):
                    raise QueryError("Unsafe filename")
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
                    raise QueryError("An explicit Content-Length is required")
                if len(lengths[0]) > 20:
                    return self.error("UPLOAD_TOO_LARGE", 413, "文件超出上传限制")
                length = int(lengths[0])
                if not 0 < length <= config.limits["upload_bytes"]:
                    return self.error("UPLOAD_TOO_LARGE", 413, "文件为空或超出上传限制")
                config.data_dir.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(config.data_dir).free - length < config.limits["min_free_disk_bytes"]:
                    return self.error("DISK_LIMIT", 507, "磁盘剩余空间不足")
                mapping = load_mapping(config.mapping_file)
                mapping_hash = input_mapping_hash(mapping, filename)
                folder = contained_path(config.data_dir, "uploads", str(uuid4()))
                folder.mkdir(parents=True)
                path = folder / filename
                digest = hashlib.sha256()
                remaining = length
                self._unread_body = length
                self.connection.settimeout(config.limits["query_timeout_seconds"])
                with path.open("xb") as outgoing:
                    while remaining:
                        block = self.rfile.read(min(1024*1024, remaining))
                        if not block:
                            raise QueryError("Incomplete upload")
                        outgoing.write(block); digest.update(block); remaining -= len(block)
                        self._unread_body = remaining
                job = store.submit_job(path, digest.hexdigest(), mapping_hash, metadata={"original_filename": filename, "input_bytes": length, "mapping_version": mapping["version"]})
                # Duplicate requests keep one canonical original rather than
                # retaining an unbounded duplicate private upload each time.
                if contained_path(config.data_dir, job.get("source_path", path)) != path.resolve():
                    path.unlink(); folder.rmdir()
                return self.response(public_job(job), 202)
            except (QueryError, ValueError, KeyError, TypeError):
                return self.error("INVALID_UPLOAD", 400, "上传参数无效；CSV 文件名必须是小写逻辑表名")
            except Exception:
                return self.error("IMPORT_UNAVAILABLE", 503, "文件登记失败；请检查服务状态后重试", True)

        def do_OPTIONS(self):
            if self.boundary():
                self.error("METHOD_NOT_ALLOWED", 405, "仅支持同源本机访问")

        def do_PUT(self):
            if self.boundary():
                self.error("METHOD_NOT_ALLOWED", 405, "此接口不支持该操作")
        do_DELETE = do_PUT
        do_PATCH = do_PUT

    return Handler


def serve(config):
    server = ThreadingHTTPServer((config.host, config.port), make_handler(config))
    server.daemon_threads = True
    print(json.dumps({"event": "http_started", "url": f"http://{config.host}:{server.server_port}/"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
