"""Versioned, lossless full-snapshot CSV reception, without legacy target globals."""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.append(str(SCRIPTS))
from csv_batch_model import build_snapshot, infer_definition
from csv_batch_store import typed_value

IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")
MODEL_VERSION = "local-server-model/1"
DATETIME_LEXICAL = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.(?P<fraction>[0-9]+))?(?:Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))\Z")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_mapping(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or not isinstance(value.get("version"), str) or not value["version"]:
        raise ValueError("Mapping requires an explicit nonempty version")
    value.setdefault("schema_version", "1")
    value.setdefault("definitions", {"tables": {}})
    value.setdefault("relations", [])
    for table, spec in value["definitions"].get("tables", {}).items():
        if not IDENTIFIER.fullmatch(table):
            raise ValueError("Invalid mapping table identifier")
        for field, definition in spec.get("columns", {}).items():
            if not IDENTIFIER.fullmatch(field):
                raise ValueError("Invalid mapping field identifier")
            # This pure conversion rejects unsupported types before SQL is touched.
            from csv_batch_store import sql_type
            sql_type(definition)
            if field == "id" and sql_type(definition) != "TEXT":
                raise ValueError("Source primary keys must retain their original text")
    for rule in value["relations"]:
        if rule.get("kind") not in {"scalar", "delimited", "polymorphic"}:
            raise ValueError("Unsupported relation rule kind")
        if not all(IDENTIFIER.fullmatch(rule.get(key, "")) for key in ("source_table", "field")):
            raise ValueError("Invalid relation rule identifier")
        if rule["kind"] != "polymorphic" and not IDENTIFIER.fullmatch(rule.get("target_table", "")):
            raise ValueError("Invalid relation target identifier")
    value["sha256"] = canonical_hash(value)
    return value


def input_mapping_hash(mapping, filename):
    """CSV filenames select a logical table; ZIP already hashes its member names."""
    path = Path(filename)
    base = mapping.get("base_sha256", mapping["sha256"])
    if path.suffix.lower() == ".csv":
        if not IDENTIFIER.fullmatch(path.stem):
            raise ValueError("CSV filename must identify a safe logical table")
        return canonical_hash({"mapping_sha256": base, "csv_table": path.stem})
    return base


def _limits(limits):
    result = {"upload_bytes": 64 * 1024 * 1024, "expanded_bytes": 256 * 1024 * 1024,
              "archive_members": 1000, "max_rows": 1000000, "max_compression_ratio": 200,
              "numeric_digits": 4096}
    result.update(limits or {})
    if "max_upload_bytes" in result:
        result["upload_bytes"] = result["max_upload_bytes"]
    return result


def _check_datetime(value):
    """Check lexical form and precision before any permissive Python parser."""
    match = DATETIME_LEXICAL.fullmatch(value.strip())
    if match is None:
        raise ValueError("Source date-time requires YYYY-MM-DDTHH:MM:SS with an XSD timezone")
    if len((match["fraction"] or "").rstrip("0")) > 6:
        raise ValueError("Source date-time exceeds exact PostgreSQL microsecond precision")


def _preflight_typed_cells(tables, metadata, definitions, limits):
    """Bound raw numerics before int()/fixed-point conversion; reject lossy time."""
    shared = {}
    for spec in definitions.get("tables", {}).values():
        for field, definition in spec.get("columns", {}).items():
            shared.setdefault(field, []).append(definition)
    numeric_bytes = 0
    for table, rows in tables.items():
        for field in metadata[table]["header"]:
            values = [row[field] for row in rows if row[field].strip()]
            definition = definitions.get("tables", {}).get(table, {}).get("columns", {}).get(field)
            if definition is None and field in shared:
                kinds = {(str(item.get("type", "string")), item.get("format"), item.get("unit")) for item in shared[field]}
                if len(kinds) == 1:
                    definition = shared[field][0]
            if definition is None:
                # Legacy inference parses *_at values. Check their untouched
                # strings first so its permissive parser cannot hide precision.
                if field.endswith("_at"):
                    for value in values:
                        _check_datetime(value)
                definition = infer_definition(field, values)
            if definition.get("format") == "date-time":
                for value in values:
                    _check_datetime(value)
            kind = definition.get("type", "string")
            if isinstance(kind, list):
                kind = next((item for item in kind if item != "null"), "string")
            if kind not in {"number", "integer"}:
                continue
            for value in values:
                try:
                    number = Decimal(value.strip())
                except InvalidOperation:
                    raise ValueError("Invalid numeric typed source value") from None
                if not number.is_finite():
                    raise ValueError("Non-finite numeric typed source value")
                exponent = number.as_tuple().exponent
                # Reading Decimal metadata never expands a scientific exponent.
                digits = max(number.adjusted() + 1, -exponent, len(number.as_tuple().digits))
                if (number.adjusted() > 131071 or exponent < -16383 or exponent > 131071
                        or digits > limits["numeric_digits"]):
                    raise ValueError("Source numeric exceeds exact supported precision bounds")
                numeric_bytes += digits + 3
                if numeric_bytes > limits["expanded_bytes"]:
                    raise ValueError("Expanded numeric byte limit exceeded")


def _member_path(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError("Unsafe ZIP member path")
    return path


def _read_csv(payload, name, limits, encoding="utf-8-sig"):
    table = PurePosixPath(name).stem
    if not IDENTIFIER.fullmatch(table) or len(table.encode()) > 50:
        raise ValueError("CSV filename must be a short lowercase table identifier")
    try:
        text = payload.decode(encoding, errors="strict")
        if "\x00" in text:
            raise ValueError("CSV contains NUL")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, [])
        if (not header or "id" not in header or len(header) != len(set(header))
                or any(not IDENTIFIER.fullmatch(field) or len(field.encode()) > 63 for field in header)):
            raise ValueError("CSV header requires unique safe names and an id")
        rows, ends = [], []
        for values in reader:
            if not values:
                continue
            if len(values) != len(header):
                raise ValueError("CSV column count differs at line " + str(reader.line_num))
            if len(rows) >= limits["max_rows"]:
                raise ValueError("CSV row limit exceeded")
            rows.append(dict(zip(header, values)))
            ends.append(reader.line_num)
    except (UnicodeError, csv.Error) as error:
        raise ValueError("Invalid CSV encoding or syntax") from error
    return table, rows, {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                         "encoding": encoding, "header": header, "row_count": len(rows), "line_ends": ends,
                         "member_role": "csv", "is_csv": True}


def prepare_input(source, destination, limits=None, *, encoding="utf-8-sig"):
    limits = _limits(limits)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source.suffix.lower() not in {".csv", ".zip"}:
        raise ValueError("Input must be a CSV or ZIP full snapshot")
    if not source.is_file() or source.stat().st_size > limits["upload_bytes"]:
        raise ValueError("Upload byte limit exceeded")
    destination.mkdir(parents=True, exist_ok=True)
    original = destination / ("source-original" + source.suffix.lower())
    if original.exists():
        if file_hash(original) != file_hash(source):
            raise ValueError("Private original changed; refusing overwrite")
    else:
        with source.open("rb") as incoming, original.open("xb") as outgoing:
            copied = 0
            while block := incoming.read(1024 * 1024):
                copied += len(block)
                if copied > limits["upload_bytes"]:
                    raise ValueError("Upload byte limit exceeded during original retention")
                outgoing.write(block)
    tables, metadata, members, total, total_rows = {}, {}, [], 0, 0
    extracted = destination / "extracted"
    extracted.mkdir(exist_ok=True)

    def receive(name, payload):
        nonlocal total, total_rows
        _member_path(name)
        total += len(payload)
        if total > limits["expanded_bytes"]:
            raise ValueError("Expanded upload limit exceeded")
        if PurePosixPath(name).suffix.lower() != ".csv":
            raise ValueError("Full snapshot archive may contain only CSV files")
        table, rows, info = _read_csv(payload, name, {**limits, "max_rows": limits["max_rows"] - total_rows}, encoding)
        total_rows += len(rows)
        if table in tables:
            raise ValueError("Repeated logical CSV table")
        target = (extracted / name).resolve()
        if not target.is_relative_to(extracted.resolve()):
            raise ValueError("CSV extraction path escapes destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        tables[table], metadata[table] = rows, info
        members.append(info)

    if source.suffix.lower() == ".csv":
        receive(source.name, original.read_bytes())
    else:
        try:
            with zipfile.ZipFile(original) as archive:
                entries = archive.infolist()
                if len(entries) > limits["archive_members"]:
                    raise ValueError("ZIP member limit exceeded")
                declared_total = 0
                names = set()
                for item in entries:
                    _member_path(item.orig_filename.rstrip("/") if item.is_dir() else item.orig_filename)
                    if item.is_dir():
                        _member_path(item.filename.rstrip("/"))
                        continue
                    _member_path(item.filename)
                    if (item.filename.casefold() in names or item.flag_bits & 1
                            or stat.S_ISLNK(item.external_attr >> 16)):
                        raise ValueError("Unsafe duplicate, encrypted, or symlink ZIP member path")
                    names.add(item.filename.casefold())
                    declared_total += item.file_size
                    if (declared_total > limits["expanded_bytes"]
                            or item.file_size > max(1, item.compress_size) * limits["max_compression_ratio"]):
                        raise ValueError("ZIP expansion limit exceeded")
                for item in entries:
                    if not item.is_dir():
                        receive(item.filename, archive.read(item))
        except zipfile.BadZipFile as error:
            raise ValueError("Invalid ZIP archive") from error
    if not tables:
        raise ValueError("Full snapshot contains no CSV tables")
    return {"archive_sha256": file_hash(original), "members": members, "csv_file_count": len(tables),
            "csv_status": "passed", "original_path": str(original)}, tables, metadata


def build_batch(source, work_dir, mapping, limits=None):
    mapping = {**mapping, "base_sha256": mapping.get("base_sha256", mapping["sha256"]),
               "sha256": input_mapping_hash(mapping, Path(source).name)}
    manifest, tables, metadata = prepare_input(source, work_dir, limits, encoding=mapping.get("encoding", "utf-8-sig"))
    _preflight_typed_cells(tables, metadata, mapping["definitions"], _limits(limits))
    package_sha = manifest["archive_sha256"]
    batch_id = canonical_hash({"source_sha256": package_sha, "mapping_sha256": mapping["sha256"],
                               "schema_version": mapping["schema_version"], "model_version": MODEL_VERSION})
    snapshot, report = build_snapshot(tables, mapping["definitions"], mapping["relations"], package_sha, metadata=metadata)
    if not snapshot["nodes"]:
        raise ValueError("An empty snapshot cannot be published")
    if any(report[key] for key in ("invalid_typed_cells", "duplicate_rows", "conflicting_rows", "quarantined_rows")):
        raise ValueError("CSV identity or typed cell validation failed")
    for node in snapshot["nodes"]:
        for field, definition in snapshot["schema"]["tables"][node["table_name"]]["columns"].items():
            value = typed_value(node["properties"][field], definition)
            if isinstance(value, Decimal) and (value.adjusted() > 131071 or value.as_tuple().exponent < -16383):
                raise ValueError("Source numeric exceeds exact PostgreSQL numeric bounds")
    snapshot.update(source_schema="ls_batch_" + batch_id[:24], dataset_label=mapping.get("dataset_label", "Imported CSV snapshot"),
                    dataset_nature="imported_unverified", batch_id=batch_id)
    return {"batch_id": batch_id, "snapshot": snapshot, "model": report, "manifest": manifest,
            "metadata": metadata, "original_path": manifest["original_path"], "mapping": mapping,
            "namespace": "urn:lzo:local-server:v1:" + batch_id + ":"}
