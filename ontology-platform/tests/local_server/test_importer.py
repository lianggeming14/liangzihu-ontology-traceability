"""Input regressions: unsafe archives and lossy typed imports must be rejected."""
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def mapping(tmp_path):
    document = {"version": "test-1", "schema_version": "1", "definitions": {"tables": {
        "ponds": {"columns": {"id": {"type": "string"}, "farm_id": {"type": "string"},
                              "area": {"type": "number"}}}}},
        "relations": [{"kind": "scalar", "source_table": "ponds", "field": "farm_id", "target_table": "farms"}]}
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def package(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            member = zipfile.ZipInfo(name)
            member.filename = name  # Preserve adversarial Windows separators in the ZIP fixture.
            archive.writestr(member, content)
    return path


def test_full_snapshot_preserves_decimal_unresolved_reference_and_line_number(tmp_path):
    from local_server.importer import build_batch, load_mapping
    source = package(tmp_path / "batch.zip", {"farms.csv": "id,name\nf1,Farm\n",
        "ponds.csv": "id,farm_id,area\np1,f1,123456789012345678.123456789\np2,absent,2.0\n"})
    batch = build_batch(source, tmp_path / "work", load_mapping(mapping(tmp_path)))
    snapshot = batch["snapshot"]
    assert snapshot["nodes"][1]["properties"]["area"] == "123456789012345678.123456789"
    assert [e["resolution"] for e in snapshot["relations"]] == ["resolved", "unresolved"]
    assert snapshot["relations"][1]["to_node"] is None
    assert batch["metadata"]["ponds"]["line_ends"] == [2, 3]
    assert Path(batch["original_path"]).read_bytes() == source.read_bytes()
    assert snapshot["dataset_nature"] == "imported_unverified"


@pytest.mark.parametrize("name", ["../evil.csv", "/absolute.csv", "C:/evil.csv", "a\\evil.csv"])
def test_zip_rejects_escaping_members(tmp_path, name):
    from local_server.importer import build_batch, load_mapping
    source = package(tmp_path / "bad.zip", {name: "id\nx\n"})
    with pytest.raises(ValueError, match="path"):
        build_batch(source, tmp_path / "work", load_mapping(mapping(tmp_path)))
    assert not (tmp_path / "evil.csv").exists()


def test_csv_size_duplicate_columns_and_invalid_types_fail(tmp_path):
    from local_server.importer import build_batch, load_mapping
    rules = load_mapping(mapping(tmp_path))
    source = tmp_path / "ponds.csv"
    source.write_text("id,farm_id,area\np1,f1,nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="typed"):
        build_batch(source, tmp_path / "a", rules)
    with pytest.raises(ValueError, match="limit"):
        build_batch(source, tmp_path / "b", rules, {"max_upload_bytes": 3})
    source.write_text("id,id\np1,p1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        build_batch(source, tmp_path / "c", rules)


def test_source_and_mapping_versions_both_change_batch_identity(tmp_path):
    from local_server.importer import build_batch, load_mapping
    source = tmp_path / "farms.csv"
    source.write_text("id,name\nf1,Farm\n", encoding="utf-8")
    path = mapping(tmp_path)
    first = build_batch(source, tmp_path / "first", load_mapping(path))
    value = json.loads(path.read_text())
    value["version"] = "test-2"
    path.write_text(json.dumps(value))
    second = build_batch(source, tmp_path / "second", load_mapping(path))
    assert first["batch_id"] != second["batch_id"]
    assert first["snapshot"]["package_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first["snapshot"]["nodes"][0]["node_id"] == second["snapshot"]["nodes"][0]["node_id"]
    source.write_text("id,name\nf1,Different farm\n", encoding="utf-8")
    third = build_batch(source, tmp_path / "third", load_mapping(path))
    assert second["snapshot"]["nodes"][0]["node_id"] != third["snapshot"]["nodes"][0]["node_id"]


def test_total_rows_and_extreme_numeric_exponents_are_bounded(tmp_path):
    from local_server.importer import build_batch, load_mapping
    rules = load_mapping(mapping(tmp_path))
    source = package(tmp_path / "batch.zip", {"farms.csv": "id\nf1\n", "ponds.csv": "id,farm_id,area\np1,f1,1\n"})
    with pytest.raises(ValueError, match="row limit"):
        build_batch(source, tmp_path / "rows", rules, {"max_rows": 1})
    source = tmp_path / "ponds.csv"
    source.write_text("id,area\np1,1e999999999\n", encoding="utf-8")
    with pytest.raises(ValueError, match="numeric"):
        build_batch(source, tmp_path / "numeric", rules)


def test_empty_snapshot_and_nontext_primary_key_mapping_are_rejected(tmp_path):
    from local_server.importer import build_batch, load_mapping
    source = tmp_path / "farms.csv"
    source.write_text("id,name\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        build_batch(source, tmp_path / "empty", load_mapping(mapping(tmp_path)))
    path = mapping(tmp_path)
    value = json.loads(path.read_text())
    value["definitions"]["tables"]["ponds"]["columns"]["id"] = {"type": "integer"}
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="text"):
        load_mapping(path)


def test_single_csv_table_name_is_part_of_effective_mapping_identity(tmp_path):
    from local_server.importer import build_batch, load_mapping, input_mapping_hash
    rules = load_mapping(mapping(tmp_path))
    farms, ponds = tmp_path / "farms.csv", tmp_path / "ponds.csv"
    farms.write_text("id,name\none,Example\n", encoding="utf-8")
    ponds.write_bytes(farms.read_bytes())
    assert input_mapping_hash(rules, farms.name) != input_mapping_hash(rules, ponds.name)
    first = build_batch(farms, tmp_path / "a", rules)
    second = build_batch(ponds, tmp_path / "b", rules)
    assert first["batch_id"] != second["batch_id"]
    assert first["snapshot"]["source_schema"] != second["snapshot"]["source_schema"]


@pytest.mark.parametrize("value", [
    "2026-11-12 12:00:00.123456789+00:00",
    "2026-11-12t12:00:00.123456789+00:00",
    "2026-11-12T12:00:00.123456789+00:00",
    "2026-11-12T12:00:00.123456789Z",
    "2026-11-12T12:00+00:00",
    "20261112T120000+00:00",
    "2026-11-12T12:00:00+00:00:00.123456789",
    "2026-11-12T12:00:00,123456+00:00",
    "2026-11-12T12:00:00+23:00",
])
def test_datetime_is_validated_before_lossy_model_parsing(tmp_path, monkeypatch, value):
    from local_server import importer
    path = mapping(tmp_path)
    document = json.loads(path.read_text())
    document["definitions"]["tables"]["ponds"]["columns"]["observed_at"] = {"type": "string", "format": "date-time"}
    path.write_text(json.dumps(document))
    source = tmp_path / "ponds.csv"
    # csv.writer quotes the comma variant while preserving the adversarial cell.
    import csv
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "observed_at"])
        writer.writerow(["p1", value])
    monkeypatch.setattr(importer, "build_snapshot", lambda *args, **kwargs: pytest.fail("Lossy datetime reached the shared parser"))
    with pytest.raises(ValueError, match="date-time"):
        importer.build_batch(source, tmp_path / "work", importer.load_mapping(path))


@pytest.mark.parametrize("kind", ["integer", "number"])
@pytest.mark.parametrize("value", ["1e999999999", "-1e999999999", "1e200000", "1e-999999999", "0e999999999"])
def test_numeric_exponents_are_rejected_before_integer_or_fixed_point_expansion(tmp_path, monkeypatch, kind, value):
    from local_server import importer
    path = mapping(tmp_path)
    document = json.loads(path.read_text())
    document["definitions"]["tables"]["ponds"]["columns"]["count"] = {"type": kind}
    path.write_text(json.dumps(document))
    source = tmp_path / "ponds.csv"
    source.write_text("id,count\np1," + value + "\n", encoding="utf-8")
    # This barrier prevents the RED run itself from ever expanding an unsafe int.
    monkeypatch.setattr(importer, "build_snapshot", lambda *args, **kwargs: pytest.fail("Unbounded numeric reached the shared model"))
    with pytest.raises(ValueError, match="numeric"):
        importer.build_batch(source, tmp_path / "work", importer.load_mapping(path))


@pytest.mark.parametrize("value", ["2026-11-12T12:00:00.123456+08:00", "2026-11-12T12:00:00.123456000Z"])
def test_exact_supported_datetime_values_remain_unchanged(tmp_path, value):
    from local_server.importer import build_batch, load_mapping
    path = mapping(tmp_path)
    document = json.loads(path.read_text())
    document["definitions"]["tables"]["ponds"]["columns"]["observed_at"] = {"type": "string", "format": "date-time"}
    path.write_text(json.dumps(document))
    source = tmp_path / "ponds.csv"
    source.write_text("id,observed_at\np1," + value + "\n", encoding="utf-8")
    result = build_batch(source, tmp_path / "work", load_mapping(path))
    assert result["snapshot"]["nodes"][0]["properties"]["observed_at"] == value
    assert result["snapshot"]["raw"][0]["payload"]["observed_at"] == value


@pytest.mark.parametrize("origin", ["inferred", "shared_dictionary"])
def test_preflight_uses_inferred_and_shared_field_definitions(tmp_path, monkeypatch, origin):
    from local_server import importer
    path = mapping(tmp_path)
    document = json.loads(path.read_text())
    if origin == "shared_dictionary":
        document["definitions"]["tables"]["other"] = {"columns": {"count": {"type": "integer"}}}
    path.write_text(json.dumps(document))
    source = tmp_path / "ponds.csv"
    source.write_text("id,count\np1,1e999999999\n", encoding="utf-8")
    monkeypatch.setattr(importer, "build_snapshot", lambda *args, **kwargs: pytest.fail("Preflight did not resolve the effective definition"))
    with pytest.raises(ValueError, match="numeric"):
        importer.build_batch(source, tmp_path / "work", importer.load_mapping(path))


def test_inferred_datetime_rejects_nanoseconds_before_the_inference_parser(tmp_path, monkeypatch):
    from local_server import importer
    source = tmp_path / "ponds.csv"
    source.write_text("id,observed_at\np1,2026-11-12 12:00:00.123456789+00:00\n", encoding="utf-8")
    real_inference = importer.infer_definition

    def inference(field, values):
        if field == "observed_at":
            pytest.fail("Nanoseconds reached legacy datetime inference")
        return real_inference(field, values)

    monkeypatch.setattr(importer, "infer_definition", inference)
    with pytest.raises(ValueError, match="date-time"):
        importer.build_batch(source, tmp_path / "work", importer.load_mapping(mapping(tmp_path)))


def test_numeric_expansion_budget_is_configurable_and_applies_before_model(tmp_path, monkeypatch):
    from local_server import importer
    source = tmp_path / "ponds.csv"
    source.write_text("id,area\np1,1e32\n", encoding="utf-8")
    rules = importer.load_mapping(mapping(tmp_path))
    real_model = importer.build_snapshot
    monkeypatch.setattr(importer, "build_snapshot", lambda *args, **kwargs: pytest.fail("Configured digit budget was bypassed"))
    with pytest.raises(ValueError, match="numeric"):
        importer.build_batch(source, tmp_path / "rejected", rules, {"numeric_digits": 32})
    monkeypatch.setattr(importer, "build_snapshot", real_model)
    assert importer.build_batch(source, tmp_path / "accepted", rules, {"numeric_digits": 33})["snapshot"]["nodes"][0]["properties"]["area"] == "1E+32"
