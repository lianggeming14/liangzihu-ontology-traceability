"""Integration tests: generated SQLite databases must enforce their contract."""
import copy
from contextlib import closing
import csv
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from database_io import build_database, load_csv_directory, write_csv


SCHEMA = {
    "tables": {
        "documents": {
            "primary_key": ["id"], "required": ["id", "current_version_id", "published_at"],
            "columns": {"id": {"type": "string"}, "current_version_id": {"type": "string"},
                        "published_at": {"type": "string", "format": "date"}},
            "foreign_keys": [{"field": "current_version_id", "references": {"table": "document_versions", "field": "id"}}],
        },
        "document_versions": {
            "primary_key": ["id"], "required": ["id", "document_id", "active", "count", "amount"],
            "columns": {"id": {"type": "string"}, "document_id": {"type": "string"},
                        "active": {"type": "boolean"}, "count": {"type": "integer"},
                        "amount": {"type": "number"}, "note": {"type": ["string", "null"]}},
            "foreign_keys": [{"field": "document_id", "references": {"table": "documents", "field": "id"}}],
        },
        "record_provenance": {"columns": {"id": {"type": "string"}}},
    },
    "table_roles": {"documents": "asset_index", "document_versions": "metadata"},
}


class DatabaseIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tables = {
            "documents": [{"id": "D1", "current_version_id": "V1", "published_at": date(2025, 1, 2)}],
            "document_versions": [{"id": "V1", "document_id": "D1", "active": True,
                                   "count": 3, "amount": 12.25, "note": None}],
        }
        self.write_tables()

    def tearDown(self):
        self.tmp.cleanup()

    def write_tables(self):
        for name, rows in self.tables.items():
            write_csv(self.root / "data" / (name + ".csv"), rows)

    def test_cycle_import_roundtrips_csv_with_types_and_counts(self):
        # Removing deferred constraints or CSV parsing breaks real import equivalence.
        report = build_database(self.root, self.tables, SCHEMA)
        self.assertEqual((report["tables"], report["rows"], report["foreign_keys"], report["errors"]), (2, 2, 2, 0))
        self.assertEqual(report["integrity_check"], "ok")
        self.assertTrue(report["csv_roundtrip"])
        with closing(sqlite3.connect(report["database_path"])) as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute("SELECT active, count, amount, note FROM document_versions").fetchone(), (1, 3, 12.25, None))
            self.assertEqual(db.execute("SELECT published_at FROM documents").fetchone(), ("2025-01-02",))
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='record_provenance'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT strict FROM pragma_table_list WHERE name='documents'").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE document_versions SET count='bad'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE document_versions SET active=2")
            db.rollback()
        parsed = load_csv_directory(self.root, SCHEMA)
        self.assertIs(parsed["document_versions"][0]["active"], True)
        self.assertIs(type(parsed["document_versions"][0]["count"]), int)
        self.assertEqual(parsed["documents"][0]["published_at"], "2025-01-02")
        with (self.root / "schema/import_manifest.csv").open(encoding="utf-8-sig", newline="") as f:
            manifest = list(csv.DictReader(f))
        self.assertEqual([r["table_role"] for r in manifest], ["asset_index", "metadata"])

    def test_new_grade_foreign_keys_and_unbounded_numeric_limits(self):
        self.tables = {
            "species": [{"id": "S1"}],
            "grade_definitions": [{"id": "G1", "species_id": "S1", "lower_bound_g": None,
                                   "upper_bound_g": 500.0, "lower_inclusive": False, "upper_inclusive": True}],
            "harvests": [{"id": "H1"}],
            "harvest_grade_items": [{"id": "I1", "grade_definition_id": "G1"}],
            "harvest_grade_individuals": [{"id": "X1", "harvest_id": "H1", "harvest_grade_item_id": "I1", "grade_definition_id": "G1"}],
        }
        # Each test only exposes supplied tables; old unrelated CSVs must not be imported.
        for path in (self.root / "data").glob("*.csv"):
            path.unlink()
        self.write_tables()
        report = build_database(self.root, self.tables, {"tables": {}})
        self.assertEqual(report["foreign_keys"], 5)
        with closing(sqlite3.connect(report["database_path"])) as db:
            info = {r[1]: r for r in db.execute("PRAGMA table_info(grade_definitions)")}
            self.assertEqual(info["lower_bound_g"][2:4], ("REAL", 0))
            self.assertEqual(info["upper_bound_g"][3], 0)
            self.assertEqual(db.execute("SELECT lower_bound_g FROM grade_definitions").fetchone(), (None,))
            db.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE grade_definitions SET species_id='absent'")
                db.commit()
            db.rollback()

    def test_bad_typed_values_are_rejected_without_zero_substitution(self):
        for field, bad in [("count", "3"), ("count", 3.5), ("active", "false"),
                           ("amount", float("nan")), ("amount", float("inf")), ("id", None)]:
            with self.subTest(field=field, bad=bad):
                values = copy.deepcopy(self.tables)
                values["document_versions"][0][field] = bad
                with self.assertRaises((ValueError, TypeError, sqlite3.IntegrityError)):
                    build_database(self.root, values, SCHEMA)
        self.assertFalse((self.root / "database/wuchang_2025.sqlite").exists())

    def test_orphan_and_duplicate_keys_cannot_replace_existing_database(self):
        report = build_database(self.root, self.tables, SCHEMA)
        original = Path(report["database_path"]).read_bytes()
        values = copy.deepcopy(self.tables)
        values["documents"][0]["current_version_id"] = "missing"
        write_csv(self.root / "data/documents.csv", values["documents"])
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            build_database(self.root, values, SCHEMA)
        self.assertEqual(Path(report["database_path"]).read_bytes(), original)
        self.write_tables()
        values = copy.deepcopy(self.tables)
        values["document_versions"].append(dict(values["document_versions"][0]))
        write_csv(self.root / "data/document_versions.csv", values["document_versions"])
        with self.assertRaises(sqlite3.IntegrityError):
            build_database(self.root, values, SCHEMA)

    def test_csv_data_mismatch_and_malformed_boolean_raise(self):
        write_csv(self.root / "data/document_versions.csv", [{**self.tables["document_versions"][0], "amount": 999.0}])
        with self.assertRaisesRegex(ValueError, "CSV|csv"):
            build_database(self.root, self.tables, SCHEMA)
        self.write_tables()
        build_database(self.root, self.tables, SCHEMA)
        path = self.root / "data/document_versions.csv"
        path.write_text(path.read_text(encoding="utf-8-sig").replace("true", "yes"), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_csv_directory(self.root, SCHEMA)

    def test_missing_foreign_key_target_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "document_versions"):
            build_database(self.root, {"documents": self.tables["documents"]}, SCHEMA)

    def test_empty_csv_can_keep_explicit_schema(self):
        tables = {"empty": []}
        schema = {"tables": {"empty": {"primary_key": ["id"], "required": ["id"],
                  "columns": {"id": {"type": "string"}, "amount": {"type": ["number", "null"]}}}}}
        write_csv(self.root / "data/empty.csv", [], ["id", "amount"])
        report = build_database(self.root, tables, schema)
        self.assertEqual((report["tables"], report["rows"]), (1, 0))

    def test_prebuild_csv_loader_preserves_declared_nonnullable_types(self):
        # A missing required list does not make a non-null declared integer nullable.
        schema = {"tables": {"metrics": {"columns": {"id": {"type": "string"}, "count": {"type": "integer"}}}}}
        write_csv(self.root / "data/metrics.csv", [{"id": "M1", "count": None}])
        with self.assertRaises(ValueError):
            load_csv_directory(self.root, schema)


if __name__ == "__main__":
    unittest.main()
