"""Streaming RDF projection and exact, disk-indexed term readback for new batches."""
from __future__ import annotations

from collections import Counter
import hashlib
from itertools import chain
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

import httpx
import rdflib
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from rdflib.plugins.parsers.ntriples import W3CNTriplesParser
from rdflib.plugins.serializers.nt import _quoteLiteral

from .importer import file_hash
from csv_batch_delivery import CanonicalRecords, STATE, write_classes
from fish_rdf_sample import C, LABELS, Navigation, PROV, project, triple_digest, uri_factory
from fish_rdf_validation import shapes, validate_canonical


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _provenance(batch):
    namespace, snapshot = batch["namespace"], batch["snapshot"]
    V, u = Namespace(namespace), uri_factory(namespace)
    for row in snapshot["raw"]:
        info = batch["metadata"][row["table_name"]]
        source = u("source", row["table_name"], row["row_number"])
        yield source, V.sourceMember, Literal(info["path"])
        yield source, V.sourceMemberSHA256, Literal(info["sha256"])
        yield source, V.csvLineEnd, Literal(info["line_ends"][row["row_number"] - 1])


def generate_rdf(batch, directory, *, progress=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path, inventory = directory / "batch.nt", directory / "term-inventory.sqlite3"
    emit = progress or (lambda value: None)
    vocabulary, subjects = Graph(), set()
    count = 0
    with sqlite3.connect(inventory) as index, path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as stream:
        index.execute("PRAGMA cache_size=-8192")
        index.execute("CREATE TABLE IF NOT EXISTS terms (digest BLOB PRIMARY KEY, seen INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID")
        index.execute("DELETE FROM terms")
        triples = chain(project(batch["snapshot"], namespace=batch["namespace"], state=STATE,
                                labels=batch["mapping"].get("labels"), table_domains=batch["mapping"].get("table_domains")),
                        _provenance(batch))
        for s, p, o in triples:
            digest = triple_digest(s, p, o)
            if index.execute("INSERT OR IGNORE INTO terms(digest) VALUES (?)", (digest,)).rowcount == 0:
                continue
            stream.write(s.n3() + " " + p.n3() + " " + (_quoteLiteral(o) if isinstance(o, Literal) else o.n3()) + " .\n")
            count += 1
            if p == RDF.type and o in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Ontology):
                subjects.add(s)
            if s in subjects or str(s).startswith(str(C)):
                vocabulary.add((s, p, o))
            if count % 1000 == 0:
                emit({"stage": "rdf_generation", "triples": count})
        hasher = hashlib.sha256()
        for (digest,) in index.execute("SELECT digest FROM terms ORDER BY digest"):
            hasher.update(digest)
        termset = hasher.hexdigest()
    vocabulary.serialize(destination=str(directory / "vocabulary.ttl"), format="turtle")
    result = {"nt_path": str(path), "inventory_path": str(inventory), "vocabulary_path": str(directory / "vocabulary.ttl"),
              "nt_sha256": file_hash(path), "nt_bytes": path.stat().st_size, "triple_count": count,
              "termset_sha256": termset, "graph_iri": batch["namespace"] + "graph:" + termset,
              "namespace": batch["namespace"], "package_sha256": batch["snapshot"]["package_sha256"]}
    save_json(directory / "generation.json", result)
    emit({"stage": "rdf_generated", "triples": count})
    return result


def verify_readback(generated, returned_path, *, progress=None):
    emit = progress or (lambda value: None)
    count = 0
    with sqlite3.connect(generated["inventory_path"]) as index:
        index.execute("PRAGMA cache_size=-8192")
        index.execute("UPDATE terms SET seen=0")

        class Sink:
            def triple(self, s, p, o):
                nonlocal count
                digest = triple_digest(s, p, o)
                if index.execute("UPDATE terms SET seen=1 WHERE digest=? AND seen=0", (digest,)).rowcount != 1:
                    raise ValueError("RDF readback contains changed, unexpected, or repeated terms")
                count += 1
                if count % 1000 == 0:
                    emit({"stage": "rdf_readback", "triples": count})

        prior = rdflib.NORMALIZE_LITERALS
        try:
            rdflib.NORMALIZE_LITERALS = False
            with Path(returned_path).open(encoding="utf-8") as stream:
                W3CNTriplesParser(sink=Sink()).parse(stream)
        finally:
            rdflib.NORMALIZE_LITERALS = prior
        if count != generated["triple_count"] or index.execute("SELECT COUNT(*) FROM terms WHERE seen=0").fetchone()[0]:
            raise ValueError("RDF readback omitted expected terms")
        hasher = hashlib.sha256()
        for (digest,) in index.execute("SELECT digest FROM terms ORDER BY digest"):
            hasher.update(digest)
        if hasher.hexdigest() != generated["termset_sha256"]:
            raise ValueError("RDF term inventory hash changed")
    return {"contract": "local-server-rdf-readback/1", "status": "passed", "full_terms_equal": True,
            "triple_count": count, "graph_iri": generated["graph_iri"], "namespace": generated["namespace"],
            "termset_sha256": generated["termset_sha256"], "nt_sha256": generated["nt_sha256"],
            "package_sha256": generated["package_sha256"], "unexpected_or_missing_terms": 0}


def _chunks(path, maximum=4 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        block, size = [], 0
        for line in stream:
            block.append(line)
            size += len(line)
            if size >= maximum:
                yield b"".join(block)
                block, size = [], 0
        if block:
            yield b"".join(block)


def load_and_verify(config, generated, *, progress=None):
    emit = progress or (lambda value: None)
    endpoint = config.fuseki_url.rstrip("/")
    url = urlsplit(endpoint)
    graph = generated["graph_iri"]
    if (url.port == 23049 or not re.fullmatch(re.escape(generated["namespace"]) + r"graph:[0-9a-f]{64}", graph)
            or file_hash(generated["nt_path"]) != generated["nt_sha256"]):
        raise ValueError("RDF target or generated content identity is unsafe")
    with httpx.Client(timeout=httpx.Timeout(600, connect=10), trust_env=False) as client:
        for block in _chunks(generated["nt_path"]):
            emit({"stage": "rdf_upload", "bytes": len(block)})
            response = client.post(endpoint + "/data", params={"graph": graph}, content=block,
                                   headers={"Content-Type": "application/n-triples"})
            response.raise_for_status()
        returned = Path(generated["nt_path"]).with_name("readback.nt")
        with client.stream("GET", endpoint + "/data", params={"graph": graph},
                           headers={"Accept": "application/n-triples", "Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            received = 0
            with returned.open("wb") as stream:
                for block in response.iter_bytes(1024 * 1024):
                    received += len(block)
                    if received > generated["nt_bytes"] * 4 + 1024 * 1024:
                        raise ValueError("RDF readback byte limit exceeded")
                    emit({"stage": "rdf_download", "bytes": len(block)})
                    stream.write(block)
    return verify_readback(generated, returned, progress=emit)


def build_navigation(batch, generated, proof, directory, *, progress=None):
    if (proof.get("status") != "passed" or proof.get("full_terms_equal") is not True
            or proof.get("graph_iri") != generated["graph_iri"]):
        raise ValueError("Public navigation requires verified RDF readback")
    directory, snapshot, namespace = Path(directory), batch["snapshot"], batch["namespace"]
    directory.mkdir(parents=True, exist_ok=True)
    vocabulary = Graph().parse(generated["vocabulary_path"], format="turtle")
    shape_graph = shapes(snapshot["schema"], vocabulary, namespace=namespace)
    navigation = Navigation(namespace=namespace, state=STATE)
    navigation.records = CanonicalRecords(snapshot, namespace)
    shacl = validate_canonical(navigation, shape_graph, namespace=namespace, progress=progress)
    if shacl["status"] != "passed" or shacl["instances_validated"] != len(snapshot["nodes"]):
        raise ValueError("Complete canonical SHACL validation failed")
    labels = {**LABELS, **batch["mapping"].get("labels", {})}
    bounded = write_classes(snapshot, namespace, batch["metadata"], labels, directory / "data", proof)
    concepts_nav = Navigation(namespace=namespace, state=STATE)
    for triple in vocabulary:
        concepts_nav.add(*triple)
    manifest, _ = concepts_nav.finish()
    counts = Counter(row["table_name"] for row in snapshot["nodes"])
    concepts = {row["iri"]: row for row in manifest["concepts"]}
    for row in concepts.values():
        row["instance_count"] = counts[row["table"]] if row["table"] else 0
        row["total_instance_count"] = row["instance_count"]
        if row["table"]:
            row["instances_path"] = "classes/csv_" + row["table"] + ".json.gz"

    def total(iri):
        row = concepts[iri]
        row["total_instance_count"] = row["instance_count"] + sum(total(child) for child in row["children"])
        return row["total_instance_count"]

    for row in concepts.values():
        if row["parent_iri"] not in concepts:
            total(row["iri"])
    manifest.update(contract="local-server-navigation/1", jena_verified=True, graph_iri=proof["graph_iri"],
                    namespace=namespace, package_sha256=snapshot["package_sha256"], batch_id=batch["batch_id"],
                    raw_payload_public=False, shacl={"status": "passed", "instances_validated": shacl["instances_validated"]})
    manifest["counts"].update(instances=len(snapshot["nodes"]), relations=len(snapshot["relations"]),
                              resolved_relations=sum(e["resolution"] == "resolved" for e in snapshot["relations"]))
    vocabulary.serialize(destination=str(directory / "vocabulary.ttl"), format="turtle")
    shape_graph.serialize(destination=str(directory / "shapes.ttl"), format="turtle")
    save_json(directory / "schema.json", snapshot["schema"])
    save_json(directory / "shacl.json", shacl)
    files = {"data/" + name: info for name, info in bounded["files"].items()}
    for name in ("vocabulary.ttl", "shapes.ttl", "schema.json", "shacl.json"):
        path = directory / name
        files[name] = {"bytes": path.stat().st_size, "sha256": file_hash(path)}
    manifest["files"] = files
    save_json(directory / "manifest.json", manifest)
    path = directory / "manifest.json"
    files = {**files, "manifest.json": {"bytes": path.stat().st_size, "sha256": file_hash(path)}}
    verify_files(directory, files)
    return {"manifest_path": str(path), "data_dir": str(directory), "manifest": manifest,
            "files": files, "shacl": shacl, "counts": manifest["counts"]}


def verify_files(directory, files):
    directory = Path(directory).resolve()
    for name, info in files.items():
        path = (directory / name).resolve()
        if (not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size != info["bytes"]
                or file_hash(path) != info["sha256"]):
            raise ValueError("Navigation file hash or safe path validation failed")
    return True
