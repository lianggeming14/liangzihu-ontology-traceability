"""Public class network from canonical navigation, with disk-backed deduplication.

The SQLite spool is temporary build state, never an application database or a
public artifact. Only one JSON instance/detail/page is decoded at a time.
"""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from rdflib import URIRef
from rdflib.namespace import RDF, RDFS, OWL

CONTRACT = "lzo-ontology-network/1"
PAGE_SIZE = 500
MAX_JSON_VALUE = 64 * 1024 * 1024
BUSINESS_KINDS = ("instance:", "object:", "layer:", "assignment:", "profile:", "activity:")
PRIVATE = (":source:", ":raw:", ":statement:", ":record:", "rawpayload", "sourcepayload", "originalpayload")


def public_iri(value):
    return (isinstance(value, str) and len(value) <= 2048
            and value.startswith(("urn:", "http://", "https://"))
            and not re.search(r'[\x00-\x20<>"{}|^`\\]', value)
            and not any(token in value.lower() for token in PRIVATE)
            and value != "http://www.w3.org/ns/prov#wasDerivedFrom"
            and value.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1].lower() != "sourcerecord")


def _path(root, relative, folders):
    if (not isinstance(relative, str) or "\\" in relative or ":" in relative
            or not re.fullmatch(r"[A-Za-z0-9_./-]+\.json(?:\.gz)?", relative)
            or any(part in ("", ".", "..") for part in relative.split("/"))
            or relative.split("/", 1)[0] not in folders):
        raise ValueError("Invalid public navigation path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Navigation file missing or outside data root")
    return path


class _JSONStream:
    """Incremental stdlib JSON decoder for a top-level envelope array."""
    def __init__(self, stream):
        self.stream, self.buffer, self.pos, self.eof = stream, "", 0, False
        self.decoder = json.JSONDecoder()

    def more(self):
        self.buffer = self.buffer[self.pos:]
        self.pos = 0
        chunk = self.stream.read(65536)
        self.buffer += chunk
        self.eof = not chunk
        if len(self.buffer) > MAX_JSON_VALUE:
            raise ValueError("Navigation JSON record exceeds bounded read limit")
        return bool(chunk)

    def peek(self):
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos].isspace():
                self.pos += 1
            if self.pos < len(self.buffer):
                return self.buffer[self.pos]
            if not self.more():
                return ""

    def take(self, expected):
        if self.peek() != expected:
            raise ValueError("Invalid navigation JSON envelope")
        self.pos += 1

    def value(self):
        self.peek()
        while True:
            try:
                value, self.pos = self.decoder.raw_decode(self.buffer, self.pos)
                return value
            except json.JSONDecodeError:
                if self.eof or not self.more():
                    raise ValueError("Truncated or invalid navigation JSON") from None


def _rows(path, field, expected=None):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        reader = _JSONStream(source)
        reader.take("{")
        found, headers = False, {}
        while reader.peek() != "}":
            key = reader.value()
            reader.take(":")
            if key == field:
                if found:
                    raise ValueError("Duplicate navigation array")
                found = True
                reader.take("[")
                while reader.peek() != "]":
                    item = reader.value()
                    if not isinstance(item, dict):
                        raise ValueError("Navigation array row must be an object")
                    yield item
                    if reader.peek() == "]":
                        break
                    reader.take(",")
                reader.take("]")
            else:
                headers[key] = reader.value()
            if reader.peek() == "}":
                break
            reader.take(",")
        reader.take("}")
        if not found or reader.peek():
            raise ValueError("Missing array or trailing navigation content")
        if any(headers.get(key) != value for key, value in (expected or {}).items()):
            raise ValueError("Navigation shard owner or direction mismatch")


def _digest(parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    # These are staging assets; the release controller publishes only after
    # verifying the full resulting inventory.
    path.write_bytes(payload)
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _build(navigation_dir, manifest, schema_graph, *, write=False):
    root = Path(navigation_dir).resolve()
    data = root / "data"
    concepts = {}
    excluded_private_classes = excluded_private_instances = 0
    for row in manifest.get("concepts", []):
        direct_count = row.get("instance_count", 0)
        if type(direct_count) is not int or direct_count < 0:
            raise ValueError("Invalid declared direct instance count")
        if public_iri(row.get("iri")):
            concepts[row["iri"]] = row
        else:
            # Private classes never become public nodes, but their exclusion
            # must remain visible in counts without disclosing their IRIs.
            excluded_private_classes += 1
            excluded_private_instances += direct_count
    namespaces = {iri.split("class:", 1)[0] for iri in concepts if "class:" in iri}
    if manifest.get("namespace"):
        namespaces.add(manifest["namespace"])
    def business(iri):
        return public_iri(iri) and any(iri.startswith(ns + kind) and len(iri) > len(ns + kind) for ns in namespaces for kind in BUSINESS_KINDS)

    verified = set()
    def read(relative, folder, field="instances", expected=None):
        path = _path(data, relative, {folder})
        metadata = manifest.get("files", {}).get("data/" + relative) or manifest.get("files", {}).get(relative)
        if metadata and relative not in verified:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != metadata["sha256"] or path.stat().st_size != metadata["bytes"]:
                raise ValueError("Navigation snapshot hash mismatch")
            verified.add(relative)
        return _rows(path, field, expected)

    with tempfile.TemporaryDirectory(prefix="ontology-network-") as temporary:
        db = sqlite3.connect(str(Path(temporary) / "aggregate.sqlite3"))
        try:
            db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; PRAGMA temp_store=FILE;"
                "CREATE TABLE nodes(id INTEGER PRIMARY KEY,iri TEXT UNIQUE,label TEXT,class_iri TEXT);"
                "CREATE TABLE records(identity TEXT PRIMARY KEY) WITHOUT ROWID;"
                "CREATE TABLE triples(s INTEGER,p TEXT,t INTEGER,n INTEGER,PRIMARY KEY(s,p,t)) WITHOUT ROWID;")
            index = {}
            for concept in concepts.values():
                declared_count = concept.get("instance_count", 0)
                if not concept.get("instances_path"):
                    if declared_count:
                        raise ValueError("Published class with direct instances has no index path")
                    continue
                accepted_count = 0
                for row in read(concept["instances_path"], "classes"):
                    iri = row.get("iri")
                    if not business(iri):
                        raise ValueError("Nonbusiness or private member in public class index")
                    if row.get("class_iri") != concept["iri"] or iri in index:
                        raise ValueError("Duplicate or mistyped published instance")
                    node_id = db.execute("INSERT INTO nodes(iri,label,class_iri) VALUES(?,?,?)", (iri, str(row.get("label") or iri), concept["iri"])).lastrowid
                    index[iri] = (node_id, concept["iri"])
                    accepted_count += 1
                if accepted_count != declared_count:
                    raise ValueError("Class index differs from declared direct instance count")
            counts = Counter(classes=len(concepts), instances=len(index), unique_record_count=0,
                             unique_triple_count=0, unresolved_count=0, excluded_private_count=0,
                             canonical_record_count=0, demo_assignment_record_count=0,
                             excluded_private_class_count=excluded_private_classes,
                             excluded_private_instance_count=excluded_private_instances)
            labels = {}
            processed = bytearray(len(index) + 1)
            def relation(owner, edge, unresolved=False, demo=False):
                if edge.get("direction", "outgoing") != "outgoing" or edge.get("inverse") is True:
                    return
                predicate = edge.get("predicate") or edge.get("iri") or edge.get("relation_iri")
                target = edge.get("target_iri")
                if not public_iri(predicate) or (target and not public_iri(target)):
                    counts["excluded_private_count"] += 1
                    return
                record = edge.get("edge_iri") or edge.get("assignment_iri")
                identity = _digest(["record", record] if record else ["relation", owner, predicate, target, edge.get("target_id")])
                if not db.execute("INSERT OR IGNORE INTO records VALUES(?)", (identity,)).rowcount:
                    return
                counts["unique_record_count"] += 1
                counts["demo_assignment_record_count" if demo else "canonical_record_count"] += 1
                if unresolved or edge.get("resolution", "resolved") != "resolved" or target not in index:
                    counts["unresolved_count"] += 1
                    return
                source_id, _ = index[owner]
                target_id, target_class = index[target]
                if edge.get("target_class_iri", target_class) != target_class:
                    raise ValueError("Resolved relation target class mismatch")
                labels.setdefault(predicate, str(edge.get("label") or predicate.rsplit(":", 1)[-1]))
                db.execute("INSERT INTO triples VALUES(?,?,?,1) ON CONFLICT(s,p,t) DO UPDATE SET n=n+1", (source_id, predicate, target_id))

            def process(row, class_iri):
                iri = row.get("iri")
                if iri not in index:
                    return
                if row.get("class_iri") != class_iri or index[iri][1] != class_iri:
                    raise ValueError("Detail instance class mismatch")
                node_id = index[iri][0]
                if processed[node_id]:
                    raise ValueError("Published detail instance is duplicated")
                processed[node_id] = 1
                outgoing_count = 0
                for edge in row.get("outgoing", []):
                    relation(iri, edge)
                    outgoing_count += 1
                for relative in row.get("outgoing_pages", []):
                    # Paths are owner-declared and contained; only outgoing page
                    # arrays are read, so inverse indexes cannot add counts.
                    for edge in read(relative, "relations", "edges", {"instance_iri": iri, "direction": "outgoing"}):
                        relation(iri, edge)
                        outgoing_count += 1
                if "outgoing_count" in row and row["outgoing_count"] != outgoing_count:
                    raise ValueError("Outgoing relation count differs from published declaration")
                for edge in row.get("unresolved_relations", []):
                    relation(iri, edge, unresolved=True)
                for edge in row.get("demo_assignments", []):
                    if edge.get("direction") == "outgoing":
                        relation(iri, edge, demo=True)

            loaded_details = set()
            for concept in concepts.values():
                if not concept.get("instances_path"):
                    continue
                for row in read(concept["instances_path"], "classes"):
                    relative = row.get("detail_path")
                    if not relative:
                        process(row, concept["iri"])
                    elif relative not in loaded_details:
                        for detail in read(relative, "details"):
                            process(detail, concept["iri"])
                        loaded_details.add(relative)
            if sum(processed) != len(index):
                raise ValueError("Published detail instances are missing")
            db.commit()
            counts["unique_triple_count"] = db.execute("SELECT count(*) FROM triples").fetchone()[0]
            nodes = [{"iri": iri, "label": str(row.get("label") or iri),
                      "parent_iri": row.get("parent_iri") if row.get("parent_iri") in concepts else None,
                      "instance_count": int(row.get("instance_count", 0)),
                      "total_instance_count": int(row.get("total_instance_count", row.get("instance_count", 0))),
                      "role": str(row.get("role") or "class")} for iri, row in sorted(concepts.items())]
            edges = []
            def edge(source, predicate, target, kind, count, label, records=None):
                value = {"id": _digest([kind, source, predicate, target]), "source": source, "target": target,
                         "predicate": predicate, "label": label, "kind": kind, "count": count, "direction": "outgoing"}
                if records is not None:
                    value["unique_record_count"] = records
                return value

            schema = set()
            if schema_graph is not None:
                for subject, target in schema_graph.subject_objects(RDFS.subClassOf):
                    if str(subject) in concepts and str(target) in concepts:
                        schema.add((str(subject), str(RDFS.subClassOf), str(target)))
                for predicate in schema_graph.subjects(RDF.type, OWL.ObjectProperty):
                    if not public_iri(str(predicate)):
                        continue
                    for source in schema_graph.objects(predicate, RDFS.domain):
                        for target in schema_graph.objects(predicate, RDFS.range):
                            if str(source) in concepts and str(target) in concepts:
                                schema.add((str(source), str(predicate), str(target)))
                for source, predicate, target in sorted(schema):
                    label = str(schema_graph.value(URIRef(predicate), RDFS.label) or ("subClassOf" if predicate == str(RDFS.subClassOf) else predicate.rsplit(":", 1)[-1]))
                    edges.append(edge(source, predicate, target, "schema", 1, label))
            query = "SELECT a.class_iri,t.p,b.class_iri,count(*),sum(t.n) FROM triples t JOIN nodes a ON a.id=t.s JOIN nodes b ON b.id=t.t GROUP BY a.class_iri,t.p,b.class_iri ORDER BY a.class_iri,t.p,b.class_iri"
            for source, predicate, target, count, records in db.execute(query):
                edges.append(edge(source, predicate, target, "observed", count, labels[predicate], records))
            counts.update(schema_edge_count=len(schema), observed_edge_count=len(edges)-len(schema))
            result = {"contract": CONTRACT, "available": True, "nodes": nodes, "edges": edges, "counts": dict(counts),
                      "schema_available": schema_graph is not None, "raw_payload_public": False,
                      "demo_assignments_nature": "synthetic"}
            if write:
                db.execute("CREATE INDEX triples_predicate ON triples(p)")
                result["relation_index"] = {}
                for link in edges:
                    if link["kind"] != "observed":
                        continue
                    pages = []
                    rows = db.execute("SELECT a.iri,a.label,a.class_iri,t.p,b.iri,b.label,b.class_iri,t.n FROM triples t JOIN nodes a ON a.id=t.s JOIN nodes b ON b.id=t.t WHERE a.class_iri=? AND t.p=? AND b.class_iri=? ORDER BY a.iri,b.iri", (link["source"], link["predicate"], link["target"]))
                    while chunk := rows.fetchmany(PAGE_SIZE):
                        items = [dict(zip(("source_iri", "source_label", "source_class_iri", "predicate", "target_iri", "target_label", "target_class_iri", "record_count"), row), direction="outgoing") for row in chunk]
                        relative = f"data/network-relations/{link['id']}/{len(pages)+1:05d}.json"
                        page = {"contract": "lzo-network-relations/1", "edge_id": link["id"], "items": items}
                        pages.append({"path": relative, "count": len(items), **_save(root / relative, page)})
                    result["relation_index"][link["id"]] = {"count": link["count"], "page_size": PAGE_SIZE, "pages": pages}
                _save(data / "ontology-network.json", result)
            return result
        finally:
            db.close()


def build_network(navigation_dir: Path, manifest: dict, *, schema_graph=None) -> dict:
    return _build(navigation_dir, manifest, schema_graph)


def write_network(navigation_dir: Path, manifest: dict, *, schema_graph=None) -> dict:
    return _build(navigation_dir, manifest, schema_graph, write=True)
