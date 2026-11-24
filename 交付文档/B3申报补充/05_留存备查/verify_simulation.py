"""Count and hash the frozen CSV batch, then write a reproducible UTF-8 inventory."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        header = next(reader)
        if not header or "" in header or len(set(header)) != len(header):
            raise ValueError(f"{path.name}: invalid header")
        count = 0
        for count, row in enumerate(reader, start=1):
            if len(row) != len(header) or not any(row):
                raise ValueError(f"{path.name}: invalid data record {count}")
        return header, count


def collect(csv_dir, manifest_path, roles_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    roles = json.loads(roles_path.read_text(encoding="utf-8-sig"))
    expected = {entry["path"]: entry for entry in manifest["members"] if entry["is_csv"]}
    with (csv_dir / "source_registry.csv").open(encoding="utf-8-sig", newline="") as source:
        origins = {row["table"]: row["origin_kind"] for row in csv.DictReader(source)}
    origins["source_registry"] = "batch_source_register"
    rows = []
    names = set()
    for path in sorted(csv_dir.glob("*.csv")):
        name = path.stem
        header, count = read_csv(path)
        digest = sha256(path)
        size = path.stat().st_size
        public = expected.pop("csv/" + path.name)
        if (count, header, digest, size) != (public["row_count"], public["header"], public["sha256"], public["bytes"]):
            raise ValueError(f"{path.name}: differs from frozen batch")
        names.update(header)
        rows.append({
            "table_name": name, "description": roles[name]["description_zh"],
            "table_role": roles[name]["role"], "origin_kind": origins[name],
            "row_count": count, "header_count": len(header), "cell_count": count * len(header),
            "bytes": size, "sha256": digest,
        })
    if expected:
        raise ValueError(f"missing source tables: {sorted(expected)}")
    summary = {"csv_file_count": len(rows), "record_count": sum(r["row_count"] for r in rows),
               "header_positions": sum(r["header_count"] for r in rows),
               "unique_header_names": len(names), "cells": sum(r["cell_count"] for r in rows),
               "source_zip_sha256": manifest["archive_sha256"], "all_files_match_source": True}
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--table-roles", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="write the by-table inventory to this CSV path")
    args = parser.parse_args()
    rows, summary = collect(args.csv_dir, args.source_manifest, args.table_roles)
    if args.out:
        with args.out.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys(), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
