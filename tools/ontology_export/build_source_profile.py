"""Build the reviewed Liangzihu source adapter from the accepted mapping export.

Offline and deterministic: reads schema/workbook metadata, never a live database.
Run from any directory; output is the versioned integration artifact directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "outputs/liangzihu-ontology-20261015"
DESTINATION = ROOT / "implementation/integrations/liangzihu"
SOURCE_COMMIT = "9995fc20cd84093adcaa3fab954ffe9d08b9f45a"
CORE_TABLES = ("users", "objects", "production_batches", "data_sources", "devices", "points", "point_bindings")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _array(value):
    return json.loads(value) if isinstance(value, str) else value


def _secret(name):
    if name in {"credential_id", "credential_ids"}:
        return False  # Agricultural quality certificates are business records.
    return bool(re.search(r"(^|_)(password|secret|credential|token|otp|totp|mfa|passkey|private_key|auth_version|recovery_code)(_|$)", name))


def _transform(column, row):
    if column["sql_type"].lower() == "uuid":
        return "uuid"
    if column["sql_type"].lower() == "date":
        return "date"
    if row["cardinality"] == "many":
        return "text_array"
    return {"decimal": "decimal", "datetime": "datetime", "integer": "integer"}.get(row["value_type"], "identity")


def build_profile(catalog, workbook):
    if catalog["source"]["commit"] != SOURCE_COMMIT:
        raise ValueError("Source commit changed: review the workbook and increment the profile version first")
    sheets = {sheet["name"]: sheet["rows"] for sheet in workbook["sheets"]}
    types = {row["source_table"]: row for row in sheets["对象类型"] if row.get("source_table")}
    properties = {(row["source_table"], row["source_column"]): row for row in sheets["属性定义"]}
    predicates = {(row["source_table"], row["source_constraint"]): row for row in sheets["关系类型"]}
    schemas = {table["name"]: table for table in catalog["tables"]}
    profile = {"source_id": "liangzihu-platform", "profile_id": "liangzihu-source-records", "version": "1.0.0",
               "label": "梁子湖来源记录映射（已核对 Excel 结构）", "tables": []}
    coverage = {"format": "liangzihu-source-coverage/1", "source": catalog["source"], "profile_id": profile["profile_id"],
                "profile_version": profile["version"], "tables": [], "fields": [], "relations": [],
                "limitations": ["只执行已接受映射中的类型、属性和值域、显式外键，不复制全部 PostgreSQL CHECK/触发器/唯一约束。",
                                "来源记录类并不等价于某个统一农业业务本体；objects.kind 保留实物类别。",
                                "复杂载荷仅保留为未映射来源证据，不进入属性推理；凭据字段拒收。",
                                "源库删除不自动级联；null 仅清除提供字段的映射，字段缺省是部分更新。",
                                "本导出没有生产实例，synthetic 示例不能视为现场接入验收。"]}
    for name, schema in schemas.items():
        type_row = types[name]
        enabled = type_row["enabled"]
        row = {"table": name, "primary_key": schema["primary_key"],
               "key_types": {column["name"]: "uuid" if column["sql_type"].lower() == "uuid" else "string"
                             for column in schema["columns"] if column["name"] in schema["primary_key"]},
               "type_ref": {"package_id": type_row["package_id"], "version": type_row["version"], "type_id": type_row["type_id"]},
               "name_prefix": type_row["label"], "fields": [], "relations": [], "deferred_fields": [], "rejected_fields": []}
        safe_names = [column["name"] for column in schema["columns"]
                      if properties[(name, column["name"])]["enabled"]]
        for preferred in ("name", "display_name", "title", "code", "external_id", "metric", "label", "username"):
            if preferred in safe_names:
                row["name_field"] = preferred
                break
        coverage["tables"].append({"table": name, "label": type_row["label"], "status": "mapped" if enabled else "catalog_only",
                                   "type_ref": row["type_ref"], "primary_key": schema["primary_key"], "source": schema["source"],
                                   "reason": "已核对的来源记录类" if enabled else type_row["notes"]})
        linked_columns = set()
        for relation in schema["foreign_keys"]:
            definition = predicates[(name, relation["name"])]
            target_table = definition["target_table"]
            relation_enabled = enabled and definition["enabled"]
            if relation_enabled and relation["referenced_columns"] != schemas[target_table]["primary_key"]:
                raise ValueError("Non-primary foreign key needs an explicit target-key resolver: " + relation["name"])
            reason = "显式外键按来源身份绑定转换；方向为引用方到被引用方" if relation_enabled else definition["notes"]
            coverage["relations"].append({"table": name, "constraint": relation["name"], "status": "mapped" if relation_enabled else "deferred",
                                          "fields": relation["columns"], "target_table": target_table,
                                          "target_fields": relation["referenced_columns"], "predicate_id": definition["predicate_id"],
                                          "reason": reason, "source": relation["source"]})
            if relation_enabled:
                row["relations"].append({"relation_key": relation["name"], "fields": relation["columns"], "target_table": target_table,
                                         "target_fields": relation["referenced_columns"], "nullable": definition["source_optional"],
                                         "predicate_ref": {"package_id": definition["package_id"], "version": definition["version"],
                                                           "predicate_id": definition["predicate_id"]}})
                linked_columns.update(relation["columns"])
        for column in schema["columns"]:
            field = column["name"]
            definition = properties[(name, field)]
            rejected = _secret(field) or definition["handling"] in {"deferred_credentials", "deferred_identity_policy"}
            if rejected:
                status = "rejected"
                reason = "来源认证、身份核验或安全控制字段不得进入普通来源映射；不能赋予本库权限。"
                if enabled:
                    row["rejected_fields"].append(field)
            elif not enabled:
                status, reason = "catalog_only", definition["notes"]
            elif definition["enabled"]:
                status, reason = "mapped_attribute", definition["notes"]
                row["fields"].append({"source_field": field, "property_id": definition["property_id"],
                                      "transform": _transform(column, definition)})
            elif field in linked_columns:
                status, reason = "mapped_relation_key", "按显式 FK 解析到目标实体；不再复制为第二份普通文本属性。"
            elif field in schema["primary_key"]:
                status, reason = "mapped_identity", "复合主键的一部分，规范化后参与来源身份绑定。"
            else:
                status, reason = "deferred", definition["notes"]
                row["deferred_fields"].append({"field": field, "reason": reason})
            coverage["fields"].append({"table": name, "field": field, "sql_type": column["sql_type"], "status": status,
                                       "property_id": definition["property_id"], "reason": reason,
                                       "nullable": column["nullable"], "primary_key": column["primary_key"], "source": column["source"]})
        if enabled:
            profile["tables"].append(row)
    coverage["counts"] = {"source_tables": len(coverage["tables"]), "source_fields": len(coverage["fields"]),
                           "source_relations": len(coverage["relations"]), "mapped_tables": len(profile["tables"]),
                           "mapped_properties": sum(len(t["fields"]) for t in profile["tables"]),
                           "mapped_relations": sum(len(t["relations"]) for t in profile["tables"]),
                           "field_statuses": dict(Counter(row["status"] for row in coverage["fields"]))}
    expected = (190, 2114, 555, 122, 979, 409)
    actual = tuple(coverage["counts"][key] for key in ("source_tables", "source_fields", "source_relations", "mapped_tables", "mapped_properties", "mapped_relations"))
    if actual != expected:
        raise ValueError(f"Accepted mapping coverage changed: expected {expected}; got {actual}")
    return profile, coverage


def export_sql(profile, catalog, tables=None):
    """PostgreSQL/psql JSONL export, deliberately excluding all deferred fields."""
    schema_by_name = {table["name"]: table for table in catalog["tables"]}
    lines = ["-- 固定结构提交 " + SOURCE_COMMIT, "-- 只读白名单导出；没有认证字段、未映射 JSON、几何、二进制或向量。",
             "-- psql --no-psqlrc --quiet --tuples-only --no-align --set ON_ERROR_STOP=1 --file readonly-export.sql --output records.jsonl",
             "-- 使用有权访问所需业务表的只读账号；生产导出文件放 implementation/runtime/source-imports/（已忽略），不得提交 Git。",
             "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;", "SET LOCAL statement_timeout = '120s';", "SET LOCAL client_encoding = 'UTF8';"]
    for table in profile["tables"]:
        if tables is not None and table["table"] not in tables:
            continue
        schema = schema_by_name[table["table"]]
        selected = set(table["primary_key"]) | {f["source_field"] for f in table["fields"]}
        selected |= {field for relation in table["relations"] for field in relation["fields"]}
        columns = []
        for column in schema["columns"]:
            name = column["name"]
            if name not in selected:
                continue
            identifier = '"' + name + '"'
            kind = column["sql_type"].lower()
            if re.match(r"^(numeric|decimal|real|double precision|float[48]?|smallint|integer|bigint|int[248]?|smallserial|serial|bigserial)\b", kind) or kind == "uuid":
                expression = identifier + "::text"
            elif kind in {"timestamptz", "timestamp with time zone"}:
                expression = "to_char(" + identifier + " AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
            elif kind.startswith("timestamp") or kind == "date":
                expression = identifier + "::text"  # No invented timezone for an unzoned timestamp.
            else:
                expression = identifier
            columns.append("    " + expression + " AS " + identifier)
        table_name = table["table"]
        order = ", ".join('"' + key + '"' for key in table["primary_key"])
        lines.append("SELECT jsonb_build_object('table', '" + table_name + "', 'values', to_jsonb(export_row))::text\nFROM (\n  SELECT\n" +
                     ",\n".join(columns) + '\n  FROM "' + schema["schema"] + '"."' + table_name + '"\n  ORDER BY ' + order + "\n) AS export_row;")
    lines.append("COMMIT;")
    return "\n\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-dir", type=Path, default=EXPORT)
    parser.add_argument("--output-dir", type=Path, default=DESTINATION)
    args = parser.parse_args(argv)
    catalog = _load(args.export_dir / "schema_catalog.json")
    workbook = _load(args.export_dir / "workbook_data.json")
    profile, coverage = build_profile(catalog, workbook)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _save(args.output_dir / "source-profile.json", profile)
    _save(args.output_dir / "coverage-manifest.json", coverage)
    package_manifest = _load(args.export_dir / "packages/manifest.json")
    packages = []
    for item in package_manifest["packages"]:
        filename = item["file"]
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise ValueError("Invalid reviewed package filename")
        raw = (args.export_dir / "packages" / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Reviewed package checksum changed: " + filename)
        package = json.loads(raw.decode("utf-8-sig"))
        if (package["package_id"], package["version"]) != (item["package_id"], item["version"]):
            raise ValueError("Reviewed package identity mismatch")
        packages.append(package)
    if len(packages) != 18:
        raise ValueError("The accepted mapping contains exactly 18 packages")
    _save(args.output_dir / "package-bundle.json", {"format": "liangzihu-reviewed-package-bundle/1", "source_commit": SOURCE_COMMIT, "packages": packages})
    for filename, tables in (("readonly-export.sql", None), ("readonly-export-core.sql", CORE_TABLES)):
        (args.output_dir / filename).write_text(export_sql(profile, catalog, tables), encoding="utf-8")
    manifest = {"format": "liangzihu-adapter-artifacts/1", "source_commit": SOURCE_COMMIT,
                "mapping_workbook": "outputs/liangzihu-ontology-20261015/梁子湖项目_本体与关系全量结构导出.xlsx",
                "profile_id": profile["profile_id"], "profile_version": profile["version"], "counts": coverage["counts"],
                "files": {name: hashlib.sha256((args.output_dir / name).read_bytes()).hexdigest()
                          for name in ("source-profile.json", "coverage-manifest.json", "package-bundle.json", "readonly-export.sql", "readonly-export-core.sql")},
                "inputs": {name: hashlib.sha256((args.export_dir / name).read_bytes()).hexdigest()
                           for name in ("schema_catalog.json", "workbook_data.json", "packages/manifest.json")}}
    _save(args.output_dir / "artifact-manifest.json", manifest)
    print(json.dumps({"output_dir": str(args.output_dir), "counts": coverage["counts"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
