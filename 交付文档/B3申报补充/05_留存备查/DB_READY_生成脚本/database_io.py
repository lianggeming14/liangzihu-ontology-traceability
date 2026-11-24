"""Typed, transactional SQLite import with an independent CSV import check.

Only caller-supplied tables are imported. The original schema contributes
constraints for retained columns; it never causes baseline data to be read.
"""
from __future__ import annotations

import csv
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any


DB_NAME = "wuchang_2025.sqlite"
TYPE_SQL = {"string": "TEXT", "integer": "INTEGER", "number": "REAL", "boolean": "INTEGER"}
MANIFEST_FIELDS = ["table_name", "table_role", "csv_path", "row_count", "db_row_count", "column_count", "sha256"]


def _quote(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (float, Decimal)) and not math.isfinite(value):
        raise ValueError("Nonfinite numeric values cannot be written to CSV")
    if not isinstance(value, (str, int, float, Decimal)):
        raise TypeError(f"Unsupported CSV value type: {type(value).__name__}")
    return str(value)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    """Write UTF-8 CSV in caller column order, with true/false and ISO dates."""
    path = Path(path)
    rows = list(rows)
    columns = list(fieldnames if fieldnames is not None else (rows[0] if rows else []))
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("CSV needs distinct fieldnames, including for an empty table")
    for row in rows:
        if set(row) != set(columns):
            raise ValueError(f"CSV row columns differ from header for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _serialize(row[column]) for column in columns})


def _inside(destination: Path, relative: str) -> Path:
    path = (destination / relative).resolve()
    if not path.is_relative_to(destination.resolve()):
        raise ValueError(f"CSV path leaves destination: {relative}")
    return path


def _csv_paths(destination: Path, names: list[str], schema: dict) -> dict[str, Path]:
    found: dict[str, list[Path]] = {}
    for path in destination.rglob("*.csv"):
        found.setdefault(path.stem, []).append(path)
    result = {}
    for name in names:
        explicit = schema.get("tables", {}).get(name, {}).get("csv_path")
        if explicit:
            path = _inside(destination, explicit)
            if not path.is_file():
                raise ValueError(f"Missing CSV for {name}: {path}")
        else:
            options = found.get(name, [])
            if len(options) != 1:
                raise ValueError(f"Expected one CSV for {name}, found {len(options)}")
            path = options[0]
        result[name] = path
    return result


def _header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        result = next(csv.reader(stream), [])
    if not result or len(result) != len(set(result)) or any(not c for c in result):
        raise ValueError(f"Invalid or duplicate CSV header: {path}")
    return result


def _dictionary_nullable() -> dict[tuple[str, str], bool]:
    path = Path(__file__).resolve().parents[2] / "schemas" / "field_dictionary.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {(r["table"], r["column"]): r["nullable"].lower() == "true"
                for r in csv.DictReader(stream)}


def _infer_type(values: list, column: str) -> str:
    values = [v for v in values if v is not None and v != ""]
    kinds = set()
    for value in values:
        if isinstance(value, bool):
            kinds.add("boolean")
        elif isinstance(value, int):
            kinds.add("integer")
        elif isinstance(value, (float, Decimal)):
            kinds.add("number")
        elif isinstance(value, (str, date, datetime)):
            kinds.add("string")
        else:
            raise TypeError(f"Unsupported inferred type for {column}: {type(value).__name__}")
    if kinds <= {"integer", "number"} and kinds:
        return "number" if "number" in kinds else "integer"
    if len(kinds) > 1:
        raise TypeError(f"Mixed incompatible types in {column}: {sorted(kinds)}")
    if kinds:
        return kinds.pop()
    if column in {"lower_bound_g", "upper_bound_g", "lower_weight_g", "upper_weight_g"}:
        return "number"
    return "string"


def _extra_foreign_keys(name: str, columns: dict) -> list[dict]:
    targets = {}
    if name == "grade_definitions":
        targets["species_id"] = "species"
    if name in {"harvest_grade_items", "growth_grade_items", "harvest_grade_individuals", "growth_individuals"}:
        targets["grade_definition_id"] = "grade_definitions"
    if name == "growth_individuals":
        targets["species_id"] = "species"
    if name == "harvest_grade_individuals":
        targets.update({"harvest_id": "harvests", "harvest_grade_item_id": "harvest_grade_items",
                        "grade_item_id": "harvest_grade_items"})
    return [{"field": field, "references": {"table": table, "field": "id"}}
            for field, table in targets.items() if field in columns]


def _effective_schema(destination: Path, tables: dict, schema: dict, paths: dict) -> dict:
    dictionary = _dictionary_nullable()
    definitions = {}
    for name, rows in tables.items():
        _quote(name)
        declared = schema.get("tables", {}).get(name, {})
        columns = list(rows[0]) if rows else _header(paths[name])
        if _header(paths[name]) != columns:
            raise ValueError(f"CSV column order differs from supplied table: {name}")
        for index, row in enumerate(rows, 1):
            if set(row) != set(columns):
                raise ValueError(f"Inconsistent columns in {name} row {index}")
        primary_key = list(declared.get("primary_key", ["id"] if "id" in columns else []))
        if any(key not in columns for key in primary_key):
            raise ValueError(f"Missing primary key column in {name}: {primary_key}")
        definitions[name] = {
            "columns": {}, "primary_key": primary_key, "foreign_keys": [],
            "csv_path": paths[name].relative_to(destination).as_posix(),
            "table_role": schema.get("table_roles", {}).get(name, declared.get("table_role", "business")),
        }
        for column in columns:
            _quote(column)
            values = [row[column] for row in rows]
            original = declared.get("columns", {}).get(column)
            if original is not None:
                data_type = original["type"]
                kinds = data_type if isinstance(data_type, list) else [data_type]
                nonnull_kinds = [k for k in kinds if k != "null"]
                if len(nonnull_kinds) != 1 or nonnull_kinds[0] not in TYPE_SQL:
                    raise ValueError(f"Unsupported declared type for {name}.{column}: {data_type}")
                kind = nonnull_kinds[0]
                nullable = "null" in kinds or original.get("nullable") is True
                if "required" in declared:
                    nullable = column not in declared["required"]
                elif (name, column) in dictionary:
                    nullable = dictionary[name, column]
                fmt = original.get("format")
            else:
                kind = _infer_type(values, column)
                nullable = not values or any(v is None or v == "" for v in values)
                fmt = None
            # Null endpoints mean an open, unbounded numeric interval.
            if name == "grade_definitions" and column in {"lower_bound_g", "upper_bound_g"}:
                nullable = True
                kind = "number"
            if column in primary_key:
                nullable = False
            definitions[name]["columns"][column] = {"type": kind, "nullable": nullable}
            if fmt:
                definitions[name]["columns"][column]["format"] = fmt
        foreign_keys = declared.get("foreign_keys", []) + _extra_foreign_keys(name, definitions[name]["columns"])
        signatures = set()
        for foreign_key in foreign_keys:
            field = foreign_key["field"]
            if field not in columns:
                continue
            reference = foreign_key["references"]
            signature = (field, reference["table"], reference["field"])
            if signature not in signatures:
                definitions[name]["foreign_keys"].append({"field": field, "references": dict(reference)})
                signatures.add(signature)
    for name, definition in definitions.items():
        for foreign_key in definition["foreign_keys"]:
            reference = foreign_key["references"]
            target = definitions.get(reference["table"])
            if target is None or reference["field"] not in target["columns"]:
                raise ValueError(f"Missing foreign key target for {name}.{foreign_key['field']}: {reference['table']}.{reference['field']}")
    return {"schema_version": "db_ready-1.0", "tables": definitions,
            "table_roles": {n: d["table_role"] for n, d in definitions.items()}}


def _validate_value(value: Any, column: dict, location: str) -> Any:
    if value is None or value == "":
        if not column["nullable"]:
            raise ValueError(f"Required value is null or empty: {location}")
        return None
    kind = column["type"]
    if kind == "boolean":
        if type(value) is not bool:
            raise TypeError(f"Expected boolean at {location}, got {value!r}")
        return int(value)
    if kind == "integer":
        if type(value) is not int or not -(2**63) <= value < 2**63:
            raise TypeError(f"Expected 64-bit integer at {location}, got {value!r}")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(value):
            raise TypeError(f"Expected finite number at {location}, got {value!r}")
        return float(value)
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    if not isinstance(value, str):
        raise TypeError(f"Expected string at {location}, got {value!r}")
    fmt = column.get("format")
    if fmt == "date":
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError(f"Expected ISO date at {location}: {value!r}")
        date.fromisoformat(value)
    elif fmt == "date-time":
        if "T" not in value and " " not in value:
            raise ValueError(f"Expected ISO datetime at {location}: {value!r}")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _typed_rows(tables: dict, schema: dict) -> dict[str, list[tuple]]:
    result = {}
    for name, definition in schema["tables"].items():
        result[name] = [tuple(_validate_value(row[column], spec, f"{name}[{index}].{column}")
                              for column, spec in definition["columns"].items())
                        for index, row in enumerate(tables[name], 1)]
    return result


def _parse_csv(path: Path, definition: dict, name: str) -> list[dict]:
    columns = definition["columns"]
    if _header(path) != list(columns):
        raise ValueError(f"CSV header mismatch for {name}")
    result = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream), 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV row has wrong field count: {name}:{index}")
            parsed = {}
            for column, spec in columns.items():
                value = row[column]
                kind = spec["type"]
                if value == "":
                    value = None
                elif kind == "boolean":
                    if value not in {"true", "false"}:
                        raise ValueError(f"Invalid CSV boolean in {name}:{index}.{column}: {value!r}")
                    value = value == "true"
                elif kind == "integer":
                    if re.fullmatch(r"-?\d+", value) is None:
                        raise ValueError(f"Invalid CSV integer in {name}:{index}.{column}: {value!r}")
                    value = int(value)
                elif kind == "number":
                    value = float(value)
                _validate_value(value, spec, f"CSV {name}:{index}.{column}")
                parsed[column] = value
            result.append(parsed)
    return result


def load_csv_directory(destination: Path, schema: dict) -> dict[str, list[dict]]:
    """Read only registered destination CSVs using recorded or supplied types.

    After build_database(), the generated database_schema.json includes inferred
    columns and manifest paths, so the original schema is sufficient here.
    """
    destination = Path(destination).resolve()
    saved = destination / "schema/database_schema.json"
    if saved.is_file():
        effective = json.loads(saved.read_text(encoding="utf-8"))
        paths = {n: _inside(destination, d["csv_path"]) for n, d in effective["tables"].items()}
    else:
        manifest = destination / "schema/import_manifest.csv"
        if manifest.is_file():
            with manifest.open(encoding="utf-8-sig", newline="") as stream:
                names = [r["table_name"] for r in csv.DictReader(stream)]
        else:
            names = [n for n in schema.get("tables", {}) if any(destination.rglob(n + ".csv"))]
        if not names:
            raise ValueError("No registered CSV tables found")
        paths = _csv_paths(destination, names, schema)
        effective = {"tables": {}}
        dictionary = _dictionary_nullable()
        for name in names:
            declared = schema["tables"][name]
            columns = {}
            for column in _header(paths[name]):
                spec = declared.get("columns", {}).get(column)
                if spec is None:
                    raise ValueError(f"CSV column type is not declared: {name}.{column}")
                kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
                nullable = spec.get("nullable", "null" in kinds)
                if "required" in declared:
                    nullable = column not in declared["required"]
                elif (name, column) in dictionary:
                    nullable = dictionary[name, column]
                columns[column] = {**spec, "type": next(k for k in kinds if k != "null"),
                                   "nullable": nullable}
            effective["tables"][name] = {"columns": columns}
    return {name: _parse_csv(paths[name], definition, name) for name, definition in effective["tables"].items()}


def _sql(schema: dict) -> str:
    statements = ["PRAGMA foreign_keys = ON;", "BEGIN TRANSACTION;", "PRAGMA defer_foreign_keys = ON;"]
    indexes = []
    for name, definition in schema["tables"].items():
        columns = []
        for column, spec in definition["columns"].items():
            quoted = _quote(column)
            line = f"  {quoted} {TYPE_SQL[spec['type']]}"
            if not spec["nullable"]:
                line += " NOT NULL"
                if spec["type"] == "string":
                    line += f" CHECK (length({quoted}) > 0)"
            if spec["type"] == "boolean":
                line += f" CHECK ({quoted} IN (0, 1))"
            columns.append(line)
        if definition["primary_key"]:
            columns.append("  PRIMARY KEY (" + ", ".join(map(_quote, definition["primary_key"])) + ")")
        for index, foreign_key in enumerate(definition["foreign_keys"]):
            reference = foreign_key["references"]
            field = _quote(foreign_key["field"])
            columns.append(f"  FOREIGN KEY ({field}) REFERENCES {_quote(reference['table'])} ({_quote(reference['field'])}) DEFERRABLE INITIALLY DEFERRED")
            indexes.append(f"CREATE INDEX {_quote('idx_' + name + '_fk_' + str(index))} ON {_quote(name)} ({field});")
        statements.append(f"CREATE TABLE {_quote(name)} (\n" + ",\n".join(columns) + "\n) STRICT;")
    statements.extend(indexes)
    statements.append("COMMIT;")
    return "\n\n".join(statements) + "\n"


def _import(connection: sqlite3.Connection, sql: str, rows: dict, schema: dict) -> dict:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(sql)
    checks = {"row_count_errors": 0, "null_errors": 0, "duplicate_key_errors": 0,
              "foreign_key_errors": 0, "integrity_errors": 0}
    connection.execute("BEGIN TRANSACTION")
    connection.execute("PRAGMA defer_foreign_keys=ON")
    try:
        for name, definition in schema["tables"].items():
            columns = list(definition["columns"])
            statement = f"INSERT INTO {_quote(name)} ({', '.join(map(_quote, columns))}) VALUES ({', '.join('?' for _ in columns)})"
            connection.executemany(statement, rows[name])
        foreign_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        checks["foreign_key_errors"] = len(foreign_errors)
        if foreign_errors:
            raise ValueError(f"SQLite foreign_key_check failed: {foreign_errors[:10]}")
        counts = {}
        for name, definition in schema["tables"].items():
            count = connection.execute(f"SELECT count(*) FROM {_quote(name)}").fetchone()[0]
            counts[name] = count
            checks["row_count_errors"] += int(count != len(rows[name]))
            for column, spec in definition["columns"].items():
                if not spec["nullable"]:
                    checks["null_errors"] += connection.execute(f"SELECT count(*) FROM {_quote(name)} WHERE {_quote(column)} IS NULL").fetchone()[0]
            if definition["primary_key"]:
                keys = ", ".join(map(_quote, definition["primary_key"]))
                checks["duplicate_key_errors"] += connection.execute(f"SELECT count(*) FROM (SELECT {keys} FROM {_quote(name)} GROUP BY {keys} HAVING count(*) > 1)").fetchone()[0]
        integrity = [r[0] for r in connection.execute("PRAGMA integrity_check")]
        checks["integrity_errors"] = int(integrity != ["ok"])
        if any(checks.values()):
            raise ValueError(f"SQLite validation failed: {checks}, integrity={integrity}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"checks": checks, "table_counts": counts, "integrity_check": "ok"}


def build_database(destination: Path, tables: dict, schema: dict) -> dict:
    """Build a checked SQLite database; reject bad values and CSV divergence.

    A temporary database protects a previous successful output on any failure.
    A second real SQLite import from CSV must exactly equal the typed import.
    """
    destination = Path(destination).resolve()
    if not tables:
        raise ValueError("No tables supplied")
    tables = {name: list(rows) for name, rows in tables.items()}
    paths = _csv_paths(destination, list(tables), schema)
    effective = _effective_schema(destination, tables, schema, paths)
    typed = _typed_rows(tables, effective)
    csv_tables = {name: _parse_csv(paths[name], definition, name)
                  for name, definition in effective["tables"].items()}
    csv_rows = _typed_rows(csv_tables, effective)
    for name in typed:
        if typed[name] != csv_rows[name]:
            raise ValueError(f"CSV values differ from supplied typed rows for {name}")
    sql = _sql(effective)
    database_dir = destination / "database"
    schema_dir = destination / "schema"
    database_dir.mkdir(parents=True, exist_ok=True)
    schema_dir.mkdir(parents=True, exist_ok=True)
    database_path = database_dir / DB_NAME
    with tempfile.NamedTemporaryFile(prefix="import_", suffix=".sqlite", dir=database_dir, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            stats = _import(db, sql, typed, effective)
            with closing(sqlite3.connect(":memory:")) as from_csv:
                _import(from_csv, sql, csv_rows, effective)
                for name in effective["tables"]:
                    query = f"SELECT * FROM {_quote(name)} ORDER BY rowid"
                    if db.execute(query).fetchall() != from_csv.execute(query).fetchall():
                        raise ValueError(f"CSV SQLite import differs for {name}")
        # Connections are closed on both success and failure before file operations.
        temporary.replace(database_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    sql_path = schema_dir / "create_tables.sql"
    sql_path.write_text(sql, encoding="utf-8")
    (schema_dir / "database_schema.json").write_text(json.dumps(effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = []
    for name, definition in effective["tables"].items():
        manifest.append({"table_name": name, "table_role": definition["table_role"],
                         "csv_path": definition["csv_path"], "row_count": len(typed[name]),
                         "db_row_count": stats["table_counts"][name], "column_count": len(definition["columns"]),
                         "sha256": hashlib.sha256(paths[name].read_bytes()).hexdigest()})
    manifest_path = schema_dir / "import_manifest.csv"
    write_csv(manifest_path, manifest, MANIFEST_FIELDS)
    foreign_keys = sum(len(d["foreign_keys"]) for d in effective["tables"].values())
    return {"database_path": str(database_path), "sql_path": str(sql_path), "manifest_path": str(manifest_path),
            "tables": len(tables), "rows": sum(len(r) for r in typed.values()), "foreign_keys": foreign_keys,
            "errors": sum(stats["checks"].values()), "csv_roundtrip": True, **stats}
