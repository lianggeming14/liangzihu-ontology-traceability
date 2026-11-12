"""Bounded public RDF reads against one immutable release.

No arbitrary SPARQL is accepted. SourceRecord and raw cells are deliberately
outside this API; complete datasets are available only through private backups.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re

import httpx
from .config import contained_path

RDFS = "http://www.w3.org/2000/01/rdf-schema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
PROV = "http://www.w3.org/ns/prov#"


class QueryError(ValueError):
    pass


def release_path(config, release, reference):
    base = config.review_dir if release.get("path_base") == "review" else config.data_dir
    if release.get("path_base") == "review" and not release.get("legacy_snapshot"):
        raise QueryError("Only legacy releases may use the review root")
    return contained_path(base, reference)


def checked_iri(value):
    if not isinstance(value, str) or len(value) > 2048 or not value.startswith(("urn:", "http://", "https://")) or re.search(r'[\x00-\x20<>"{}|^`\\]', value):
        raise QueryError("Invalid public ontology identifier")
    return value


def encode_cursor(release_id, scope, offset):
    raw = json.dumps([str(release_id), scope, offset], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value, release_id, scope):
    try:
        if not isinstance(value, str) or len(value) > 8192 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError()
        version, request, offset = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if version != str(release_id) or request != scope or isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100000000:
            raise ValueError()
        return offset
    except (ValueError, TypeError, UnicodeError):
        raise QueryError("Cursor does not match this release and query") from None


def public_release(release):
    if release is None:
        return None
    keys = ("release_id", "created_at", "published_at", "status", "batch_id", "package_sha256", "mapping_sha256", "model_version", "schema_version", "counts", "sql_schema", "sql_schemas", "rdf_graph", "rdf_graphs", "data_nature", "read_only", "legacy_snapshot")
    return {key: release[key] for key in keys if key in release}


class QueryService:
    def __init__(self, config, release):
        self.config, self.release = config, release
        self.release_id = str(release["release_id"])
        # Old in-memory callers may pass an absolute path; containment is still
        # checked whenever the real Config declares a data root.
        manifest_path = release_path(config, release, release["manifest_path"]) if hasattr(config, "data_dir") else Path(release["manifest_path"])
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.concepts = {row["iri"]: row for row in self.manifest.get("concepts", [])}
        graphs = release.get("rdf_graphs") or [release.get("rdf_graph")]
        self.graphs = tuple(checked_iri(value) for value in graphs if value)
        if not self.graphs:
            raise QueryError("Release has no verified graph")
        namespaces = {value.split("class:", 1)[0] for value in self.concepts if "class:" in value}
        namespaces.add(release.get("namespace") or self.manifest.get("namespace", ""))
        namespaces.update(value.split("graph:", 1)[0] for value in self.graphs if "graph:" in value)
        self.namespaces = tuple(checked_iri(value) for value in namespaces if value)

    def query(self, sparql):
        with httpx.Client(timeout=self.config.limits["query_timeout_seconds"], trust_env=False) as client:
            response = client.post(self.config.fuseki_url + "/query", data={"query": sparql}, headers={"Accept": "application/sparql-results+json"})
            response.raise_for_status()
            return response.json()["results"]["bindings"]

    def dataset(self):
        return " ".join("FROM <" + value + ">" for value in self.graphs)

    def _is_business(self, value):
        # These identities belong to published business objects, never physical
        # rows, statements, datasets, provenance entities or arbitrary IRIs.
        return any(value.startswith(ns + kind) and len(value) > len(ns + kind)
                   for ns in self.namespaces for kind in ("instance:", "object:", "layer:", "assignment:", "profile:", "activity:"))

    def _public_term(self, value):
        return value in self.concepts or self._is_business(value)

    def _predicate(self, value):
        return (":raw:" not in value and value != PROV + "wasDerivedFrom"
                and not any(token in value.lower() for token in ("rawpayload", "sourcepayload", "originalpayload")))

    def _safe_outgoing(self, row):
        predicate, obj = row["predicate"]["value"], row["object"]
        if not self._predicate(predicate):
            return False
        # Public properties may reference vocabulary IRIs. Private source and
        # statement identifiers are never disclosed as navigable objects.
        if obj.get("type") == "uri" and any(token in obj["value"] for token in (":source:", ":raw:", ":statement:", ":record:")):
            return False
        return True

    def _public_filter(self, variable):
        values = [f'STRSTARTS(STR({variable}), "{ns}{kind}")' for ns in self.namespaces for kind in ("instance:", "object:", "layer:", "assignment:", "profile:", "activity:")]
        return "FILTER(" + " || ".join(values or ["false"]) + ") "

    def _property_filter(self):
        return ('FILTER(!CONTAINS(STR(?predicate), ":raw:") && ?predicate != <' + PROV + 'wasDerivedFrom>) '
                'FILTER(!isIRI(?object) || (!CONTAINS(STR(?object), ":source:") && !CONTAINS(STR(?object), ":raw:") && !CONTAINS(STR(?object), ":statement:") && !CONTAINS(STR(?object), ":record:"))) ')

    def _page(self, scope, limit=None, cursor=None, offset=0):
        try:
            limit = int(self.config.limits["page_size"] if limit is None else limit)
            offset = int(offset)
        except (ValueError, TypeError):
            raise QueryError("Invalid page") from None
        if not 1 <= limit <= self.config.limits["max_page_size"] or not 0 <= offset <= 100000000:
            raise QueryError("Invalid page")
        if cursor:
            if offset:
                raise QueryError("Use cursor or offset")
            offset = decode_cursor(cursor, self.release_id, scope)
        return limit, offset

    def _result(self, value):
        return {"release_id": self.release_id, "mode": "fuseki", **value}

    def children(self, parent):
        checked_iri(parent)
        if parent not in self.concepts and parent != self.manifest.get("root_iri"):
            raise QueryError("Choose a published ontology class")
        return self._result({"parent": parent, "items": [row for row in self.concepts.values() if row.get("parent_iri") == parent]})

    def instances(self, concept, *, limit=None, cursor=None, offset=0):
        if concept not in self.concepts:
            raise QueryError("Choose a published ontology class")
        scope = "instances:" + concept
        limit, offset = self._page(scope, limit, cursor, offset)
        query = (f"PREFIX rdfs: <{RDFS}> PREFIX rdf: <{RDF}> SELECT DISTINCT ?instance ?label {self.dataset()} WHERE {{ "
                 f"?instance rdf:type/rdfs:subClassOf* <{checked_iri(concept)}> . {self._public_filter('?instance')} "
                 "OPTIONAL { ?instance rdfs:label ?label } } ORDER BY ?instance ?label " + f"LIMIT {limit+1} OFFSET {offset}")
        rows = self.query(query)
        items = [{"iri": row["instance"]["value"], "label": row.get("label", {}).get("value", row["instance"]["value"])} for row in rows[:limit] if self._is_business(row["instance"]["value"])]
        return self._result({"class_iri": concept, "items": items, "limit": limit, "offset": offset,
            "next_offset": offset+limit if len(rows) > limit else None,
            "next_cursor": encode_cursor(self.release_id, scope, offset+limit) if len(rows) > limit else None})

    def resource(self, identifier, *, limit=None, outgoing_offset=0, incoming_offset=0, cursor=None, incoming_cursor=None):
        checked_iri(identifier)
        if not self._public_term(identifier):
            raise QueryError("Only published business objects and classes are public")
        limit, outgoing_offset = self._page("resource-out:" + identifier, limit, cursor, outgoing_offset)
        _, incoming_offset = self._page("resource-in:" + identifier, limit, incoming_cursor, incoming_offset)
        present = self.query(f"SELECT (1 AS ?exists) {self.dataset()} WHERE {{ <{identifier}> ?p ?o }} LIMIT 1")
        if not present:
            raise QueryError("Public resource is not present in this release")
        outgoing = self.query(f"SELECT DISTINCT ?predicate ?object {self.dataset()} WHERE {{ <{identifier}> ?predicate ?object . {self._property_filter()} }} ORDER BY ?predicate ?object LIMIT {limit+1} OFFSET {outgoing_offset}")
        incoming = self.query(f"SELECT DISTINCT ?subject ?predicate {self.dataset()} WHERE {{ ?subject ?predicate <{identifier}> . {self._public_filter('?subject')} }} ORDER BY ?predicate ?subject LIMIT {limit+1} OFFSET {incoming_offset}")
        return self._result({"iri": identifier, "sql_used": False, "graph_iris": self.graphs, "limit": limit,
            "outgoing": [{"predicate": row["predicate"]["value"], "object": row["object"]} for row in outgoing[:limit] if self._safe_outgoing(row)],
            "incoming": [{"subject": row["subject"]["value"], "predicate": row["predicate"]["value"]} for row in incoming[:limit] if self._is_business(row["subject"]["value"]) and self._predicate(row["predicate"]["value"])],
            "outgoing_offset": outgoing_offset, "incoming_offset": incoming_offset,
            "next_outgoing_offset": outgoing_offset+limit if len(outgoing) > limit else None,
            "next_incoming_offset": incoming_offset+limit if len(incoming) > limit else None,
            "next_cursor": encode_cursor(self.release_id, "resource-out:"+identifier, outgoing_offset+limit) if len(outgoing) > limit else None,
            "next_incoming_cursor": encode_cursor(self.release_id, "resource-in:"+identifier, incoming_offset+limit) if len(incoming) > limit else None,
            "truncated": len(outgoing) > limit or len(incoming) > limit,
            "provenance": {"release_id": self.release_id, "package_sha256": self.release.get("package_sha256"),
                "data_nature": next((row["object"]["value"] for row in outgoing if row["predicate"]["value"].endswith((":dataNature", "#dataNature", "/dataNature")) and row["object"].get("type") == "literal"), None),
                "release_data_nature": self.release.get("data_nature", "imported_unverified")}})

    def export(self, concept, *, limit=None, cursor=None):
        if concept not in self.concepts:
            raise QueryError("Choose a published ontology class")
        scope = "export:" + concept
        limit, offset = self._page(scope, limit, cursor)
        sparql = (f"PREFIX rdfs: <{RDFS}> PREFIX rdf: <{RDF}> SELECT DISTINCT ?subject ?predicate ?object {self.dataset()} WHERE {{ "
                  f"?subject rdf:type/rdfs:subClassOf* <{checked_iri(concept)}> ; ?predicate ?object . "
                  f"{self._public_filter('?subject')} {self._property_filter()} }} ORDER BY ?subject ?predicate ?object LIMIT {limit+1} OFFSET {offset}")
        rows = self.query(sparql)
        triples = [{"subject": row["subject"]["value"], "predicate": row["predicate"]["value"], "object": row["object"]} for row in rows[:limit] if self._is_business(row["subject"]["value"]) and self._safe_outgoing(row)]
        return self._result({"class_iri": concept, "items": triples, "limit": limit,
            "next_cursor": encode_cursor(self.release_id, scope, offset+limit) if len(rows) > limit else None,
            "scope": "public-normalized-triples", "raw_payload_public": False})

    def status(self):
        # A bounded ASK-shaped read per graph. Never COUNT 24M triples at startup
        # or on readiness. Full inventory belongs to backup/validation commands.
        available = all(self.query(f"SELECT (1 AS ?present) WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }} LIMIT 1") for graph in self.graphs)
        return self._result({"available": bool(available), "graph_iris": self.graphs, "read_only": True, "sql_used": False})

    def maps(self):
        directory = release_path(self.config, self.release, self.release["navigation_dir"])
        path = directory / "data" / "map-features.json"
        if not path.is_file():
            return self._result({"layers": [], "crs": None, "rfc7946": False, "message": "此版本没有地图图层"})
        if not path.resolve().is_relative_to(directory) or path.stat().st_size > 64*1024*1024:
            raise QueryError("Map asset outside public limits")
        value = json.loads(path.read_text(encoding="utf-8"))
        # Preserve explicit local image/paper spaces and source uncertainty.
        return self._result(value)
