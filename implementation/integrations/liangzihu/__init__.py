"""Pinned Liangzihu adapter artifacts and deterministic import planning.

This module has no database connection, performs no inference and never fetches
farm records. It translates operator-provided snapshots into the backend API.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import heapq
import json
from pathlib import Path
import re
from uuid import UUID

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[2]
EXPORT = ROOT / "outputs/liangzihu-ontology-20261015"
MAX_BATCH_RECORDS = 100
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON contains a duplicate field: " + key)
        result[key] = value
    return result


def strict_json(text):
    return json.loads(text, object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))


def _read_json(path):
    return strict_json(path.read_text(encoding="utf-8-sig"))


def load_profile(source_id):
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 200 or source_id != source_id.strip():
        raise ValueError("source_id must be a stable, non-empty identifier of at most 200 characters")
    manifest = _read_json(DIRECTORY / "artifact-manifest.json")
    raw = (DIRECTORY / "source-profile.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["files"]["source-profile.json"]:
        raise ValueError("Source profile does not match its reviewed artifact manifest")
    profile = strict_json(raw.decode("utf-8"))
    profile["source_id"] = source_id
    return profile


def load_bundle(source_id):
    """Preserve exact reviewed releases; never silently overwrite a release."""
    manifest = _read_json(DIRECTORY / "artifact-manifest.json")
    raw = (DIRECTORY / "package-bundle.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["files"]["package-bundle.json"]:
        raise ValueError("Reviewed package bundle checksum mismatch")
    bundle = strict_json(raw.decode("utf-8"))
    if bundle.get("format") != "liangzihu-reviewed-package-bundle/1" or bundle["source_commit"] != manifest["source_commit"]:
        raise ValueError("Reviewed package bundle baseline mismatch")
    return {"packages": bundle["packages"], "profile": load_profile(source_id)}


def read_records(path):
    """Accept an explicit envelope, a JSON array, or one record per JSONL line.

    Decimal JSON floats are kept as floats so the backend rejects them rather
    than silently pretending their original decimal precision was preserved.
    """
    path = Path(path)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds 64 MiB; export a bounded dependency-closed subset")
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        records = [strict_json(line) for line in text.splitlines() if line.strip()]
        metadata = {}
    else:
        value = strict_json(text)
        if isinstance(value, list):
            records, metadata = value, {}
        elif isinstance(value, dict) and isinstance(value.get("records"), list):
            records = value["records"]
            metadata = {key: value[key] for key in ("data_nature", "observed_at", "batch_id", "source_commit") if key in value}
        else:
            raise ValueError("Use an envelope with records, an array, or .jsonl records")
    if not records:
        raise ValueError("Input contains no records")
    if len(records) > 100000:
        raise ValueError("Input exceeds the 100,000-record planner budget")
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) - {"table", "values", "expected_revision"}:
            raise ValueError(f"Record {index + 1}: allowed keys are table, values, expected_revision")
        if not isinstance(record.get("table"), str) or not isinstance(record.get("values"), dict):
            raise ValueError(f"Record {index + 1}: table and values are required")
    return records, metadata


def canonical_key(table, values):
    key = {}
    for name in table["primary_key"]:
        if name not in values or values[name] is None:
            raise ValueError(table["table"] + ": missing primary key " + name)
        value = values[name]
        kind = table.get("key_types", {}).get(name, "string")
        if kind == "uuid":
            if not isinstance(value, str):
                raise ValueError(table["table"] + ": UUID primary key must be text")
            try:
                value = str(UUID(value))
            except (ValueError, AttributeError):
                raise ValueError(table["table"] + ": invalid UUID primary key " + name) from None
        elif kind == "integer":
            if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"-?(0|[1-9][0-9]*)", str(value)):
                raise ValueError(table["table"] + ": integer key requires decimal text or a safe JSON integer")
            if isinstance(value, int) and abs(value) > 9007199254740991:
                raise ValueError(table["table"] + ": unsafe JSON integer key; use decimal text")
            value = str(int(value))
            if len(value) > 200:
                raise ValueError(table["table"] + ": integer key exceeds 200 digits")
        elif not isinstance(value, str) or not value or len(value) > 500:
            raise ValueError(table["table"] + ": string key must contain 1–500 characters; whitespace is significant")
        key[name] = value
    return key


def _node(table, key):
    return table + ":" + canonical_bytes(key).decode("utf-8")


def make_batch(profile, records, observed_at, batch_id, data_nature="unspecified"):
    if not 1 <= len(records) <= MAX_BATCH_RECORDS:
        raise ValueError("A batch contains 1–100 records; use the plan command for larger exports")
    if not isinstance(observed_at, str):
        raise ValueError("observed_at is required: the source snapshot timestamp, not an invented business event time")
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise ValueError("observed_at requires an ISO timestamp with an explicit timezone") from None
    if not isinstance(batch_id, str) or not 1 <= len(batch_id) <= 200:
        raise ValueError("batch_id must contain 1–200 characters")
    if data_nature not in {"production", "synthetic", "test", "unspecified"}:
        raise ValueError("Invalid data_nature")
    result = {key: profile[key] for key in ("source_id", "profile_id", "version")}
    result.update({"batch_id": batch_id, "observed_at": observed_at, "records": records, "data_nature": data_nature})
    if len(canonical_bytes(result)) > MAX_REQUEST_BYTES:
        raise ValueError("Batch exceeds 2 MiB; reduce the batch size or attach large evidence by reference")
    return result


def _components(graph):
    """Iterative Kosaraju SCC: supports long source chains without recursion."""
    seen, finished = set(), []
    for start in sorted(graph):
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(sorted(graph[start])))]
        while stack:
            node, edges = stack[-1]
            try:
                other = next(edges)
            except StopIteration:
                finished.append(node)
                stack.pop()
                continue
            if other not in seen:
                seen.add(other)
                stack.append((other, iter(sorted(graph[other]))))
    reverse = {key: set() for key in graph}
    for node, targets in graph.items():
        for target in targets:
            reverse[target].add(node)
    visited, components = set(), []
    for start in reversed(finished):
        if start in visited:
            continue
        stack, group = [start], []
        visited.add(start)
        while stack:
            node = stack.pop()
            group.append(node)
            for other in sorted(reverse[node]):
                if other not in visited:
                    visited.add(other)
                    stack.append(other)
        components.append(sorted(group))
    return components


def plan_batches(profile, records, observed_at, *, existing_bindings=(), batch_size=100, data_nature="unspecified"):
    """Plan FK-closed SCC groups, parents before children. No database writes.

    Existing bindings must belong to the same source and tenant (the HTTP client
    obtains them from the authenticated endpoint). Omitted FK fields are patches;
    required-new-record constraints remain enforced by the backend preview.
    """
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be an integer from 1 to 100")
    tables = {table["table"]: table for table in profile["tables"]}
    known, revisions = set(), {}
    for binding in existing_bindings:
        if binding.get("source_id", profile["source_id"]) != profile["source_id"]:
            raise ValueError("Binding snapshot belongs to a different source")
        binding_table = binding.get("table", binding.get("source_table"))
        if binding_table not in tables:
            continue
        node = _node(binding_table, canonical_key(tables[binding_table], binding["source_key"]))
        known.add(node)
        revisions[node] = int(binding["revision"])
    by_node = {}
    for record in records:
        if record["table"] not in tables:
            raise ValueError("Table is not enabled in the reviewed profile: " + record["table"])
        table = tables[record["table"]]
        node = _node(record["table"], canonical_key(table, record["values"]))
        if node in by_node:
            raise ValueError("Duplicate source identity in input: " + record["table"])
        copy = deepcopy(record)
        if node in revisions:
            copy.setdefault("expected_revision", revisions[node])
        else:
            copy.setdefault("expected_revision", 0)
        rejected = set(table["rejected_fields"]) & set(copy["values"])
        if rejected:
            raise ValueError(record["table"] + ": rejected source fields: " + ", ".join(sorted(rejected)))
        allowed = set(table["primary_key"]) | {item["source_field"] for item in table["fields"]}
        allowed |= {field for relation in table["relations"] for field in relation["fields"]}
        allowed |= {item["field"] for item in table["deferred_fields"]}
        unknown = set(copy["values"]) - allowed
        if unknown:
            raise ValueError(record["table"] + ": unmapped source fields: " + ", ".join(sorted(unknown)))
        by_node[node] = copy
    graph = {node: set() for node in by_node}
    for node, record in by_node.items():
        for relation in tables[record["table"]]["relations"]:
            present = [field in record["values"] for field in relation["fields"]]
            if not any(present):
                if node not in known and not relation.get("nullable", False):
                    raise ValueError(record["table"] + ": new record requires foreign key " + relation["relation_key"])
                continue
            if not all(present):
                raise ValueError(record["table"] + ": incomplete composite foreign key " + relation["relation_key"])
            values = [record["values"][field] for field in relation["fields"]]
            if any(value is None for value in values):
                if not all(value is None for value in values) or not relation.get("nullable", False):
                    raise ValueError(record["table"] + ": invalid null foreign key " + relation["relation_key"])
                continue
            target = tables[relation["target_table"]]
            target_key = canonical_key(target, dict(zip(relation["target_fields"], values)))
            target_node = _node(target["table"], target_key)
            if target_node in by_node:
                graph[node].add(target_node)
            elif target_node not in known:
                raise ValueError(record["table"] + ": unresolved foreign key " + relation["relation_key"] + " -> " + target["table"])
    groups = _components(graph)
    if any(len(group) > batch_size for group in groups):
        raise ValueError("A foreign-key cycle exceeds the batch limit; enlarge --batch-size up to 100 or review the source mapping")
    group_for = {node: index for index, group in enumerate(groups) for node in group}
    dependencies = {index: {group_for[target] for node in group for target in graph[node] if group_for[target] != index}
                    for index, group in enumerate(groups)}
    consumers = {index: set() for index in dependencies}
    for index, targets in dependencies.items():
        for target in targets:
            consumers[target].add(index)
    ready = [(groups[index][0], index) for index in dependencies if not dependencies[index]]
    heapq.heapify(ready)
    ordered = []
    while ready:
        _, index = heapq.heappop(ready)
        ordered.append(groups[index])
        for consumer in sorted(consumers[index]):
            dependencies[consumer].remove(index)
            if not dependencies[consumer]:
                heapq.heappush(ready, (groups[consumer][0], consumer))
    if len(ordered) != len(groups):
        raise ValueError("Internal dependency planning error")
    plan_key = digest({"profile": profile, "records": list(by_node.values()), "observed_at": observed_at, "data_nature": data_nature})[:32]
    batches, pending = [], []
    for group in ordered:
        group_records = [by_node[node] for node in group]
        candidate = pending + group_records
        candidate_payload = {"records": candidate, "observed_at": observed_at, "batch_id": "lzhu-" + plan_key + "-999999"}
        # Reserve envelope room and do not split a mutually dependent SCC.
        if pending and (len(candidate) > batch_size or len(canonical_bytes(candidate_payload)) > MAX_REQUEST_BYTES - 2048):
            batches.append(make_batch(profile, pending, observed_at, "lzhu-" + plan_key + "-" + str(len(batches) + 1), data_nature))
            pending = []
        pending.extend(group_records)
    if pending:
        batches.append(make_batch(profile, pending, observed_at, "lzhu-" + plan_key + "-" + str(len(batches) + 1), data_nature))
    return {"format": "liangzihu-import-plan/1", "plan_id": plan_key, "source_id": profile["source_id"],
            "profile_id": profile["profile_id"], "version": profile["version"], "profile_hash": digest(profile),
            "observed_at": observed_at, "data_nature": data_nature, "record_count": len(records), "batch_count": len(batches), "batches": batches,
            "atomicity": "each_batch_only", "validation": "dependency_plan_only_backend_preview_required",
            "existing_bindings_used": len(known)}
