"""Lossless, answer-independent inspection of the Wuchangfish L1 input package.

Only synthetic_raw and format/schema metadata feed normalization. Baseline,
sample and answer files are inventoried but never used to repair source records.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path, PurePosixPath
from typing import Iterator

from lzo.ingestion.mapping import number as bounded_decimal


# Reviewed against the pinned generator/business.py calls, never inferred from
# identifier spelling or by blindly pluralizing an arbitrary source_type.
BUSINESS_SOURCE_TARGETS = {
    'inventory_movements': {'purchase_item': 'purchase_items', 'opening_balance': 'opening_balances',
                            'stocking_event': 'stocking_events', 'feeding_event': 'feeding_events'},
    'cost_entries': {'stocking_event': 'stocking_events', 'feeding_event': 'feeding_events',
                     'transfer_event': 'transfer_events', 'mortality_event': 'mortality_events'},
}
BUSINESS_EXTERNAL_SOURCE_TYPES = {
    'inventory_movements': {'pond_preparation', 'inventory_count', 'unused_feed_checkout', 'unused_feed_return'},
    'cost_entries': {'inventory_issue', 'inventory_count', 'annual_rental_contract', 'electricity_bill', 'payroll'},
}

# Pinned generator/run.py writes this exact field with ';'.join(death IDs).
# Other semicolon-bearing report/coverage strings are not business identities.
LIST_SOURCE_TARGETS = {('patrol_events', 'mortality_event_ids'): 'mortality_events'}


def list_source_links(table: str, payload: dict) -> list[dict]:
    """Keep each explicit token and ordinal; never trim/guess a source ID."""
    links = []
    for (owner, field), target in LIST_SOURCE_TARGETS.items():
        if table != owner or payload.get(field) in (None, ''):
            continue
        value = payload[field]
        if not isinstance(value, str):
            raise ValueError('Source ID list must preserve its original string')
        links.extend({'field':field, 'target_table':target, 'target_pk':token,
            'list_index':index, 'rule':'pinned-generator-semicolon-v1'}
            for index, token in enumerate(value.split(';')))
    return links


def business_source_link(table: str, payload: dict) -> dict | None:
    """Describe only proven business targets; retain vouchers without fake objects."""
    if table not in BUSINESS_SOURCE_TARGETS:
        return None
    source_type, source_id = payload.get('source_type'), payload.get('source_id')
    if source_type in (None, '') and source_id in (None, ''):
        return None
    target = BUSINESS_SOURCE_TARGETS[table].get(source_type)
    status = ('candidate' if target else 'external_reference'
              if source_type in BUSINESS_EXTERNAL_SOURCE_TYPES[table] else 'unresolved')
    if source_id in (None, ''):
        status = 'unresolved'
    return {'field': 'source_id', 'target_table': target,
            'target_pk': str(source_id) if source_id is not None else '', 'source_type': source_type,
            'status': status, 'rule': 'pinned-business-generator-source-type-v1'}


@dataclass
class FishRow:
    table: str
    row_number: int
    pk: str
    payload: dict
    normalized: dict
    issues: list[dict] = field(default_factory=list)
    status: str = "accepted"
    duplicate_of: int | None = None
    nature: str = "synthetic"

    def issue(self, code: str, column: str, severity: str = "review", **details):
        self.issues.append({"code": code, "field": column, "severity": severity, **details})
        if severity == "error":
            self.status = "quarantined"
        elif severity == "review" and self.status == "accepted":
            self.status = "needs_review"


@dataclass
class PackageAudit:
    schema: dict
    rows: dict[str, list[FishRow]]
    summary: dict
    manifest: dict
    relations: list[dict]

    def iter_rows(self) -> Iterator[FishRow]:
        for rows in self.rows.values():
            yield from rows


def _typed(value: str, spec: dict):
    if value == "" or value is None:
        return None
    types = spec.get("type", "string")
    types = types if isinstance(types, list) else [types]
    if "boolean" in types:
        if str(value).lower() not in ("true", "false"):
            raise ValueError("not boolean")
        return str(value).lower() == "true"
    if "integer" in types:
        if not re.fullmatch(r"[+-]?\d+", str(value)):
            raise ValueError("not integer")
        return int(value)
    if "number" in types:
        # JSON has no exact decimal type. A bounded fixed-point lexical string
        # preserves every digit and is valid for the schema's xsd:decimal mapping.
        return format(bounded_decimal(value), 'f')
    if spec.get("format") == "date":
        return date.fromisoformat(str(value)).isoformat()
    if spec.get("format") == "date-time":
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
        return parsed.isoformat()
    return value


def audit_rows(schema: dict, raw_tables: dict[str, list[dict]], package_sha256: str,
               *, manifest: dict | None = None) -> PackageAudit:
    """Audit without reference answers. Unproven physical anomalies stay unverified."""
    if schema.get("timezone", "Asia/Shanghai") != "Asia/Shanghai":
        raise ValueError("unsupported source timezone")
    reference_only = [t for t in schema["tables"] if t == "record_provenance"]
    expected = set(schema["tables"]) - set(reference_only)
    if expected - raw_tables.keys():
        raise ValueError("missing input table: " + ", ".join(sorted(expected - raw_tables.keys())))
    if raw_tables.keys() - expected:
        raise ValueError("unexpected input table: " + ", ".join(sorted(raw_tables.keys() - expected)))
    result: dict[str, list[FishRow]] = {}
    index: dict[str, dict[str, list[FishRow]]] = {}
    for table in sorted(expected):
        spec = schema["tables"][table]
        if spec.get("primary_key", ["id"]) != ["id"]:
            raise ValueError("unsupported primary key: " + table)
        rows = result[table] = []
        table_index = index[table] = defaultdict(list)
        for number, payload in enumerate(raw_tables[table], 2):
            row = FishRow(table, number, str(payload.get("id", "")), dict(payload), {})
            if table == "weather_observations" and payload.get("origin_kind") == "weather_reanalysis":
                row.nature = "imported_unverified"
            if table == "sources" and str(payload.get("is_synthetic", "")).lower() == "false":
                row.nature = "imported_unverified"
            if not row.pk:
                row.issue("missing_primary_key", "id", "error")
            for col, value in payload.items():
                try:
                    row.normalized[col] = _typed(value, spec.get("columns", {}).get(col, {}))
                except (ValueError, TypeError, OverflowError):
                    row.normalized[col] = None
                    row.issue("invalid_type", col, "error")
            for col, field_spec in spec.get("columns", {}).items():
                if col not in payload:
                    row.normalized[col] = None
                    row.issue("missing_column", col, "error")
                value = row.normalized.get(col)
                if value is None and col in spec.get("required", []):
                    row.issue("missing_required_value", col)
                if value is not None and "enum" in field_spec:
                    numeric = 'number' in field_spec.get('type', [])
                    allowed = (any(bounded_decimal(value) == bounded_decimal(candidate) for candidate in field_spec['enum'])
                               if numeric else value in field_spec['enum'])
                    if not allowed:
                        row.issue("outside_observed_enum", col)
            for col, source_unit in payload.items():
                if not col.endswith("_unit") or not source_unit or col in spec.get("columns", {}):
                    continue
                original = col[:-5]
                if original not in payload:
                    continue
                value = row.normalized.get(original)
                if original == "temperature_c" and source_unit == "degF":
                    if value is not None:
                        try:
                            with localcontext() as context:
                                context.prec = 144
                                converted = round((bounded_decimal(value) - Decimal(32)) / Decimal('1.8'), 9)
                            row.normalized[original] = format(bounded_decimal(converted), 'f')
                            row.issue("explicit_unit_conversion", original, "info", source_unit="degF", target_unit="degC", decimal_places=9)
                        except (ValueError, InvalidOperation):
                            row.normalized[original] = None
                            row.issue('invalid_unit_conversion', original, 'error')
                elif original == "temperature_c" and source_unit in ("degC", "°C"):
                    pass
                else:
                    row.issue("unsupported_unit", original, "error", source_unit=source_unit)
            for col, field_spec in spec.get("columns", {}).items():
                if field_spec.get("format") == "date-time" and row.normalized.get(col) is not None:
                    if datetime.fromisoformat(str(payload[col])).tzinfo is None:
                        row.issue("source_timezone_applied", col, "info", timezone="Asia/Shanghai")
            if payload.get("uploaded_at"):
                row.issue("source_upload_time_preserved", "uploaded_at", "info")
            rows.append(row)
            table_index[row.pk].append(row)
        for pk, occurrences in table_index.items():
            if len(occurrences) < 2:
                continue
            fingerprints = {json.dumps(r.payload, sort_keys=True, ensure_ascii=False) for r in occurrences}
            if len(fingerprints) > 1:
                for row in occurrences:
                    row.issue("conflicting_primary_key", "id", "error")
            else:
                for row in occurrences[1:]:
                    row.status = "duplicate"
                    row.duplicate_of = occurrences[0].row_number
                    row.issue("exact_duplicate", "id", "info", first_row=row.duplicate_of)
    relations = []
    for table, rows in result.items():
        spec = schema["tables"][table]
        for row in rows:
            links = [(fk["field"], fk["references"]["table"], row.payload.get(fk["field"]))
                     for fk in spec.get("foreign_keys", [])]
            links += [(fk["id_field"], row.payload.get(fk["table_field"]), row.payload.get(fk["id_field"]))
                      for fk in spec.get("polymorphic_foreign_keys", [])]
            business_link = business_source_link(table, row.payload)
            if business_link is not None:
                if business_link['status'] == 'candidate':
                    links.append(('source_id', business_link['target_table'], business_link['target_pk']))
                else:
                    relations.append({'table': table, 'pk': row.pk, 'row_number': row.row_number, **business_link})
                    if business_link['status'] == 'unresolved' and row.status != 'duplicate':
                        row.issue('unresolved_business_source', 'source_id', source_type=business_link['source_type'])
            for link in list_source_links(table, row.payload):
                resolved = bool(link['target_pk']) and link['target_pk'] in index.get(link['target_table'], {})
                relations.append({'table':table, 'pk':row.pk, 'row_number':row.row_number,
                    **link, 'status':'resolved' if resolved else 'unresolved'})
                if not resolved and row.status != 'duplicate':
                    row.issue('unresolved_list_foreign_key', link['field'], 'error',
                        target_table=link['target_table'], target_pk=link['target_pk'], list_index=link['list_index'])
            for column, target_table, target_pk in links:
                if target_pk in (None, ""):
                    continue
                resolved = str(target_pk) in index.get(target_table, {})
                relations.append({"table": table, "pk": row.pk, "row_number": row.row_number,
                                  "field": column, "target_table": target_table, "target_pk": str(target_pk),
                                  "status": "resolved" if resolved else "unresolved"})
                if not resolved and row.status != "duplicate":
                    row.issue("unresolved_foreign_key", column, "error", target_table=target_table, target_pk=target_pk)
    # Report unusable target identities separately from missing references, preserving every edge.
    for link in relations:
        if link["status"] == "resolved":
            targets = index[link["target_table"]][link["target_pk"]]
            if not any(r.status in ("accepted", "needs_review") for r in targets):
                link["status"] = "target_quarantined"
    table_counts = {}
    issues = Counter()
    for table, rows in result.items():
        table_counts[table] = {"physical_rows": len(rows), "unique_source_ids": len(index[table]),
                               "statuses": dict(Counter(r.status for r in rows)),
                               "source_columns": sorted({c for r in rows for c in r.payload}),
                               "schema_columns": len(schema["tables"][table]["columns"])}
        issues.update(i["code"] for r in rows for i in r.issues)
    summary = {"package_sha256": package_sha256, "input_scope": "synthetic_raw", "schema_table_count": len(schema["tables"]),
               "raw_table_count": len(result), "schema_field_count": sum(len(t["columns"]) for t in schema["tables"].values()),
               "physical_rows": sum(len(v) for v in result.values()), "tables": table_counts,
               "statuses": dict(Counter(r.status for rows in result.values() for r in rows)),
               "issue_counts": dict(issues), "reference_only_tables": reference_only,
               "relations": dict(Counter(r["status"] for r in relations)),
               "answer_key_used_for_cleaning": False, "physical_anomaly_detection": "not asserted; source values remain unverified",
               "numeric_normalization": "bounded fixed-point decimal strings; original source spelling retained in payload",
               "business_source_rule": "pinned-business-generator-source-type-v1; external vouchers are not object identities",
               "list_source_rule": "pinned-generator-semicolon-v1; patrol_events.mortality_event_ids only; tokens preserved exactly",
               "nature": "synthetic farm; ERA5 weather imported_unverified; no actual drawing identity link"}
    return PackageAudit(schema, result, summary, manifest or {}, relations)


def load_package(root: Path, manifest_path: Path) -> PackageAudit:
    """Verify archived bytes and every extracted member before reading any input rows."""
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = manifest_path.parent / "source.zip"
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("archive SHA256 mismatch")
    if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != manifest["archive_git_blob"]:
        raise ValueError("archive Git blob mismatch")
    extraction_root = root.parent
    member_paths = set()
    for member in manifest["members"]:
        path = PurePosixPath(member["path"])
        if path.is_absolute() or ".." in path.parts or "\\" in str(path) or ":" in str(path):
            raise ValueError("unsafe member path")
        local = extraction_root.joinpath(*path.parts).resolve()
        if not local.is_relative_to(extraction_root):
            raise ValueError("member escapes extraction root")
        if local in member_paths:
            raise ValueError("duplicate member path")
        member_paths.add(local)
        if not local.is_file() or local.stat().st_size != member["bytes"] or hashlib.sha256(local.read_bytes()).hexdigest() != member["sha256"]:
            raise ValueError("member hash mismatch: " + str(path))
    def read_csv(path):
        if path.resolve() not in member_paths:
            raise ValueError("input absent from verified manifest: " + str(path))
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("invalid CSV header")
            rows = list(reader)
            if any(None in row or any(v is None for v in row.values()) for row in rows):
                raise ValueError("CSV record/header width mismatch")
            return rows
    schema_path = root / "schemas/schema.json"
    if schema_path.resolve() not in member_paths:
        raise ValueError("unverified schema")
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    raw = {}
    for table in schema["tables"]:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table):
            raise ValueError("unsafe table name")
        if table != "record_provenance":
            raw[table] = read_csv(root / "synthetic_raw" / (table + ".csv"))
    audit = audit_rows(schema, raw, manifest["archive_sha256"], manifest=manifest)
    audit.summary["archive_members"] = len(manifest["members"])
    audit.summary["source_registry_rows"] = len(read_csv(root / "synthetic_raw/source_registry.csv"))
    audit.summary["source_views"] = [{"path": m["path"], "bytes": m["bytes"], "sha256": m["sha256"]}
                                     for m in manifest["members"] if m["path"].startswith("output/synthetic_raw/source_views/")]
    audit.summary["source_views_are_additional_business_events"] = False
    return audit
