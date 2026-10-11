"""Bounded, tenant-scoped CURRENT multidimensional network projection.

Relationships, material ancestry, event participation and evidence links retain
different semantics. Source evidence is never promoted into proof of all facts
about an object. This module does not reconstruct historical knowledge snapshots.
"""
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import UUID

from .service import DomainError

LABELS = {
    "identity": "对象身份", "space": "空间关系", "production": "生产关系",
    "material": "物料谱系", "event": "事件参与", "evidence": "证据来源",
    "observation": "观测", "assertion": "断言",
}
JSON_FIELDS = {"qualifiers", "evidence_ids", "value_json"}
SPECS = {
    "entities": ("entity_key", "entity_key,entity_type,name,revision", "entity_key", ["entity_key"]),
    "relations": ("id", "id,subject_key,object_key,predicate_id,dimension,valid_from,valid_to,qualifiers,evidence_ids,status,revision", "created_at,id", ["subject_key", "object_key"]),
    "events": ("id", "id,event_type,occurred_at,evidence_ids,status", "occurred_at,id", []),
    "event_participants": ("id", "id,event_id,entity_key,role,quantity,unit", "event_id,id", ["entity_key"]),
    "material_ancestry": (None, "event_id,input_lot_key,output_lot_key,allocation_status,allocation_quantity,unit", "event_id,input_lot_key,output_lot_key", ["input_lot_key", "output_lot_key"]),
    "evidence": ("id", "id,kind,public_summary,status,revision", "created_at,id", []),
    "evidence_links": ("id", "id,evidence_id,target_kind,target_id", "created_at,id", ["target_id"]),
    "observations": ("id", "id,subject_key,property_id,value_json,observed_at,method,origin,evidence_ids", "observed_at,id", ["subject_key"]),
    "assertions": ("id", "id,subject_key,predicate_id,value_json,object_key,origin,evidence_ids,status,revision", "created_at,id", ["subject_key", "object_key"]),
    "lots": ("lot_key", "lot_key,production_batch_key,product_type,unit", "lot_key", ["lot_key", "production_batch_key"]),
}


def _integer(value, default, maximum, name):
    try:
        if isinstance(value, bool):
            raise ValueError()
        result = int(str(default if value in (None, "") else value))
        if not 1 <= result <= maximum:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise DomainError(422, "invalid_graph_budget", name + " must be an integer between 1 and " + str(maximum))


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _columns(specification):
    result = []
    for column in specification.split(','):
        if column in JSON_FIELDS:
            result.append('CASE WHEN length(CAST(' + column + ' AS TEXT))<=8192 THEN ' + column + ' ELSE NULL END AS ' + column)
            result.append('CASE WHEN length(CAST(' + column + ' AS TEXT))>8192 THEN 1 ELSE 0 END AS ' + column + '_graph_omitted')
        elif column == 'public_summary':
            result.append('substr(public_summary,1,500) AS public_summary')
        else:
            result.append(column)
    return ','.join(result)


def _row(value, gaps):
    result = _plain(dict(value))
    for field in JSON_FIELDS:
        if result.pop(field + '_graph_omitted', 0):
            gaps.add('field_loading_limit:' + field + ':' + str(result.get('id', 'unknown')))
            result[field] = [] if field == 'evidence_ids' else None
    for key in JSON_FIELDS:
        if key in result and isinstance(result[key], str):
            try:
                result[key] = json.loads(result[key])
            except ValueError:
                gaps.add("invalid_json:" + key + ":" + str(result.get("id", "unknown")))
                result[key] = [] if key == "evidence_ids" else None
    return result


def _preview(value, depth=0):
    """Keep graph labels/qualifiers bounded; full records remain separate queries."""
    if depth >= 3:
        return "[详情请查看记录]"
    if isinstance(value, dict):
        return {str(k)[:80]: _preview(v, depth+1) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [_preview(v, depth+1) for v in value[:20]]
    return value[:500] if isinstance(value, str) else value


def build_network(service, tenant, actor, params=None):
    # Use the public service boundary first to perform its current read checks.
    service.query("entities", tenant, actor, {"limit": 1})
    p = params or {}
    if not isinstance(p, dict):
        raise DomainError(422, "invalid_query", "Graph parameters must be an object")
    if any(p.get(key) for key in ("valid_at", "known_at", "revision")):
        raise DomainError(422, "historical_snapshot_unsupported",
                          "Multidimensional network supports current state only")
    limit = _integer(p.get("limit"), 150, 300, "limit")
    depth = _integer(p.get("depth"), 3, 5, "depth")
    dimension = str(p.get("dimension") or "all")
    if len(dimension) > 100:
        raise DomainError(422, "invalid_dimension", "Dimension name is too long")
    center = p.get("center") or p.get("entity_key")
    if center:
        try:
            center = str(UUID(str(center)))
        except (ValueError, TypeError, AttributeError):
            raise DomainError(422, "invalid_reference", "center must be an entity UUID")

    cap = min(900, max(60, limit * 3))
    gaps = set()
    truncated_tables = set()
    rows = {}
    db = service.db

    # Every aggregation SELECT carries tenant_id. Tables/columns come only from
    # fixed SPECS, while every identifier supplied by a caller is a parameter.
    with db.transaction() as tx:
        if getattr(db, "backend", "") == "postgresql":
            tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if center:
            found = tx.execute("SELECT entity_key FROM entities WHERE tenant_id=%s AND entity_key=%s",
                               (tenant, center)).fetchone()
            if not found:
                raise DomainError(404, "entity_not_found", "Center entity not found")
        for table, (_, columns, ordering, priorities) in SPECS.items():
            args = [tenant]
            priority_sql = ""
            if center and priorities:
                priority_sql = "CASE WHEN " + " OR ".join(column + "=%s" for column in priorities) + " THEN 0 ELSE 1 END,"
                args.extend([center] * len(priorities))
            args.append(cap + 1)
            found = tx.execute(
                "SELECT " + _columns(columns) + " FROM " + table +
                " WHERE tenant_id=%s ORDER BY " + priority_sql + ordering + " LIMIT %s",
                tuple(args)).fetchall()
            if len(found) > cap:
                truncated_tables.add(table)
            rows[table] = [_row(record, gaps) for record in found[:cap]]

        def ensure(table, ids):
            key, columns, _, _ = SPECS[table]
            present = {str(row[key]) for row in rows[table]}
            missing = sorted({str(value) for value in ids if value is not None} - present)
            if len(missing) > cap:
                truncated_tables.add(table + "_reference_lookup")
            for start in range(0, min(len(missing), cap), 100):
                batch = missing[start:min(start+100, cap)]
                found = tx.execute(
                    "SELECT " + _columns(columns) + " FROM " + table +
                    " WHERE tenant_id=%s AND " + key + " IN (" + ",".join(["%s"] * len(batch)) + ")",
                    (tenant, *batch)).fetchall()
                rows[table].extend(_row(record, gaps) for record in found)

        # Referenced records may lie outside a table's initial ordered window.
        targets = defaultdict(set)
        for link in rows["evidence_links"]:
            targets[link["target_kind"]].add(link["target_id"])
        ensure("relations", targets["relation"])
        ensure("observations", targets["observation"])
        ensure("assertions", targets["assertion"])
        ensure("events", targets["event"] | {x["event_id"] for x in rows["event_participants"]} |
               {x["event_id"] for x in rows["material_ancestry"]})
        evidence_ids = {x["evidence_id"] for x in rows["evidence_links"]}
        for table in ("relations", "events", "observations", "assertions"):
            for row in rows[table]:
                evidence_ids.update(row.get("evidence_ids") or [])
        ensure("evidence", evidence_ids)
        entity_ids = {center} if center else set()
        for table, columns in (
            ("relations", ("subject_key", "object_key")),
            ("event_participants", ("entity_key",)),
            ("material_ancestry", ("input_lot_key", "output_lot_key")),
            ("observations", ("subject_key",)),
            ("assertions", ("subject_key", "object_key")),
            ("lots", ("lot_key", "production_batch_key")),
        ):
            for row in rows[table]:
                entity_ids.update(row.get(column) for column in columns)
        entity_ids.update(targets["entity"] | targets["lot"])
        ensure("entities", entity_ids)

    nodes = {}
    edges = {}
    missing_edges = 0

    def node(identifier, name, kind, dimension_id, status="current", **details):
        nodes[identifier] = {
            "id": identifier, "label": str(name)[:160], "name": str(name)[:160],
            "kind": kind, "type": kind, "dimension": dimension_id, "status": status,
            **details,
        }

    def edge(identifier, source, target, predicate, dimension_id, status="recorded", **details):
        nonlocal missing_edges
        if source not in nodes or target not in nodes:
            missing_edges += 1
            return
        edges[identifier] = {
            "id": identifier, "source": source, "target": target,
            "predicate": predicate, "predicate_id": predicate,
            "dimension": dimension_id, "status": status, **details,
        }

    for item in rows["entities"]:
        node(item["entity_key"], item["name"], item["entity_type"], "identity",
             entity_key=item["entity_key"], entity_type=item["entity_type"], revision=item["revision"])
    for item in rows["events"]:
        node("event:"+item["id"], item["event_type"], "event", "event", item["status"],
             occurred_at=item["occurred_at"], record_id=item["id"])
    for item in rows["evidence"]:
        node("evidence:"+item["id"], item["public_summary"] or item["kind"], "evidence", "evidence",
             item["status"], record_id=item["id"], evidence_kind=item["kind"], revision=item["revision"])
    for item in rows["observations"]:
        node("observation:"+item["id"], item["property_id"], "observation", "observation", item["origin"],
             record_id=item["id"], observed_at=item["observed_at"], value=_preview(item["value_json"]),
             method=item["method"])
    for item in rows["assertions"]:
        node("assertion:"+item["id"], item["predicate_id"], "assertion", "assertion", item["status"],
             record_id=item["id"], origin=item["origin"], value=_preview(item["value_json"]),
             revision=item["revision"])
    reified = {str(value) for value in targets["relation"]}
    reified.update(item["id"] for item in rows["relations"] if item.get("evidence_ids"))
    for item in rows["relations"]:
        if item["id"] in reified:
            node("relation:"+item["id"], item["predicate_id"], "relation", item["dimension"], item["status"],
                 record_id=item["id"], revision=item["revision"])

    for item in rows["relations"]:
        rid = item["id"]
        ref = "relation:"+rid if rid in reified else None
        common = {"qualifiers": _preview(item.get("qualifiers") or {}),
                  "evidence_ids": item.get("evidence_ids") or [],
                  "valid_from": item["valid_from"], "valid_to": item["valid_to"],
                  "relation_ref": ref, "record_id": rid}
        edge("relation-edge:"+rid, item["subject_key"], item["object_key"], item["predicate_id"],
             item["dimension"], item["status"], **common)
        if ref:
            edge(ref+":subject", ref, item["subject_key"], "relation_subject", item["dimension"], item["status"])
            edge(ref+":object", ref, item["object_key"], "relation_object", item["dimension"], item["status"])

    for item in rows["event_participants"]:
        event_ref = "event:"+item["event_id"]
        output_role = item["role"] in {"output", "received_item"}
        source, target = (event_ref, item["entity_key"]) if output_role else (item["entity_key"], event_ref)
        edge("participant:"+item["id"], source, target, "participates_as:"+item["role"], "event",
             role=item["role"], qualifiers={"quantity":item["quantity"],"unit":item["unit"]},
             event_ref=event_ref)
    for item in rows["material_ancestry"]:
        edge("material:"+item["event_id"]+":"+item["input_lot_key"]+":"+item["output_lot_key"],
             item["input_lot_key"], item["output_lot_key"], "materialAncestorOf", "material",
             event_ref="event:"+item["event_id"],
             qualifiers={"allocation_status":item["allocation_status"],
                         "allocation_quantity":item["allocation_quantity"],"unit":item["unit"]})
    for item in rows["lots"]:
        if item["production_batch_key"]:
            edge("production-context:"+item["lot_key"], item["production_batch_key"], item["lot_key"],
                 "production_context", "production", qualifiers={"not_material_ancestry":True})
    for item in rows["observations"]:
        edge("observes:"+item["id"], "observation:"+item["id"], item["subject_key"],
             "observes_property_of", "observation", item["origin"], property_id=item["property_id"])
    for item in rows["assertions"]:
        edge("asserts:"+item["id"], "assertion:"+item["id"], item["subject_key"],
             "asserts_about", "assertion", item["status"])
        if item["object_key"]:
            edge("assertion-object:"+item["id"], "assertion:"+item["id"], item["object_key"],
                 "asserted_object", "assertion", item["status"])

    def evidence_edge(eid, target_kind, target_id):
        target = target_id if target_kind in {"entity", "lot"} else target_kind+":"+target_id
        edge("evidence-link:"+eid+":"+target_kind+":"+target_id, "evidence:"+eid, target,
             "source_record_for", "evidence", qualifiers={"meaning":"provenance_link_not_truth_assessment"})

    for item in rows["evidence_links"]:
        evidence_edge(item["evidence_id"], item["target_kind"], item["target_id"])
    for table, kind in (("relations","relation"),("events","event"),("observations","observation"),("assertions","assertion")):
        for item in rows[table]:
            for eid in item.get("evidence_ids") or []:
                evidence_edge(eid, kind, item["id"])

    all_edges = list(edges.values())
    dimensions = sorted(set(LABELS) | {e["dimension"] for e in all_edges})
    dimension_counts = {key:sum(e["dimension"]==key for e in all_edges) for key in dimensions}
    eligible = [e for e in all_edges if dimension == "all" or e["dimension"] == dimension]
    adjacency = defaultdict(set)
    for item in eligible:
        adjacency[item["source"]].add(item["target"])
        adjacency[item["target"]].add(item["source"])
    if center:
        reachable = {center}
        distances = {center:0}
        queue = deque([center])
        while queue:
            current = queue.popleft()
            if distances[current] >= depth:
                continue
            for neighbor in sorted(adjacency[current]):
                if neighbor not in reachable:
                    reachable.add(neighbor)
                    distances[neighbor] = distances[current]+1
                    queue.append(neighbor)
        ordered = sorted(reachable, key=lambda key:(distances[key], key))
        depth_cut = any(neighbor not in reachable for key in reachable for neighbor in adjacency[key])
        if depth_cut:
            gaps.add("depth_limit:additional_connected_records_outside_requested_depth")
    else:
        # Balance dimensions before adding unrelated entities so a large entity
        # catalog cannot consume the whole budget and conceal event/evidence nodes.
        by_dimension = defaultdict(deque)
        for item in sorted(eligible, key=lambda value:value["id"]):
            by_dimension[item["dimension"]].append(item)
        ordered = []
        seen = set()
        while any(by_dimension.values()):
            for key in sorted(by_dimension):
                if by_dimension[key]:
                    item = by_dimension[key].popleft()
                    for endpoint in (item["source"],item["target"]):
                        if endpoint not in seen:
                            seen.add(endpoint); ordered.append(endpoint)
        if dimension == "all":
            ordered.extend(key for key in sorted(nodes) if key not in seen)
        depth_cut = False

    selected = set(ordered[:limit])
    selected_edges = [item for item in eligible if item["source"] in selected and item["target"] in selected]
    edge_cap = limit * 8
    edge_truncated = len(selected_edges) > edge_cap
    selected_edges = selected_edges[:edge_cap]
    if len(ordered) > limit:
        gaps.add("node_limit:increase_limit_or_narrow_the_center")
    if edge_truncated:
        gaps.add("edge_limit:parallel_relations_exceed_the_response_budget")
    if truncated_tables:
        gaps.add("loading_limit:bounded_candidate_window_may_omit_connections")
    if missing_edges:
        gaps.add("unresolved_endpoints:outside_loading_budget_or_missing_scoped_records")
    if dimension not in dimensions and dimension != "all":
        gaps.add("dimension_not_present_in_loaded_current_view")
    truncated = bool(truncated_tables or len(ordered)>limit or edge_truncated or depth_cut or missing_edges or any(gap.startswith("field_loading_limit") for gap in gaps))
    return {
        "nodes":[nodes[key] for key in ordered[:limit]],
        "edges":selected_edges,
        "dimensions":dimensions, "dimension_labels":{key:LABELS.get(key,key) for key in dimensions},
        "dimension_counts":dimension_counts,
        "truncated":truncated, "gaps":sorted(gaps),
        "counts":{"nodes":len(selected),"edges":len(selected_edges),
                  "candidate_nodes":len(nodes),"candidate_edges":len(all_edges),
                  "unresolved_edges":missing_edges,
                  "source_rows_loaded":{table:len(values) for table,values in rows.items()}},
        "query":{"center":center,"depth":depth,"dimension":dimension,"limit":limit,
                 "row_budget_per_table":cap,"reference_budget_per_table":cap,"edge_budget":edge_cap,
                 "json_field_character_limit":8192,"depth_applied":bool(center)},
        "view":{"kind":"current","historical_slice_supported":False,
                "generated_at":datetime.now(timezone.utc).isoformat(),
                "direction_for_neighborhood":"undirected_reachability_preserving_directed_edges",
                "evidence_semantics":"source links do not automatically establish truth or causality"},
    }
