"""RDF inventories must detect term changes without retaining the graph in RAM."""
from pathlib import Path
import sys

import pytest
from rdflib.namespace import OWL

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def small_batch(tmp_path):
    from local_server.importer import build_batch, load_mapping
    source = tmp_path / "ponds.csv"
    source.write_text("id,farm_id,area\np1,unknown,123456789012345678.123456789\n", encoding="utf-8")
    mapping = load_mapping(ROOT / "config/local-server-mapping.json")
    return build_batch(source, tmp_path / "batch", mapping)


def test_streamed_generation_and_full_term_readback_accept_reordered_nt(tmp_path):
    from local_server.rdf import generate_rdf, verify_readback
    batch = small_batch(tmp_path)
    generated = generate_rdf(batch, tmp_path / "rdf")
    lines = Path(generated["nt_path"]).read_bytes().splitlines(keepends=True)
    assert any(b'"123456789012345678.123456789"^^' in line for line in lines)
    assert not any(str(OWL.sameAs).encode() in line for line in lines)
    returned = tmp_path / "readback.nt"
    returned.write_bytes(b"".join(reversed(lines)))
    proof = verify_readback(generated, returned)
    assert proof["full_terms_equal"] is True
    assert proof["triple_count"] == len(lines)
    assert generated["graph_iri"].startswith(batch["namespace"] + "graph:")
    assert Path(generated["inventory_path"]).is_file()


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "changed"])
def test_readback_rejects_missing_duplicated_and_changed_terms(tmp_path, corruption):
    from local_server.rdf import generate_rdf, verify_readback
    batch = small_batch(tmp_path)
    generated = generate_rdf(batch, tmp_path / "rdf")
    lines = Path(generated["nt_path"]).read_bytes().splitlines(keepends=True)
    if corruption == "missing":
        lines.pop()
    elif corruption == "duplicate":
        lines.append(lines[-1])
    else:
        position = next(i for i, line in enumerate(lines) if b'"unknown"' in line)
        lines[position] = lines[position].replace(b'"unknown"', b'"corrupt"')
    returned = tmp_path / "readback.nt"
    returned.write_bytes(b"".join(lines))
    with pytest.raises(ValueError, match="RDF"):
        verify_readback(generated, returned)


def test_shacl_and_navigation_are_verified_and_raw_cells_are_private(tmp_path):
    from local_server.rdf import generate_rdf, verify_readback, build_navigation
    batch = small_batch(tmp_path)
    generated = generate_rdf(batch, tmp_path / "rdf")
    proof = verify_readback(generated, generated["nt_path"])
    result = build_navigation(batch, generated, proof, tmp_path / "public")
    assert result["shacl"]["status"] == "passed"
    assert result["shacl"]["instances_validated"] == 1
    assert result["counts"]["instances"] == 1
    assert result["files"]
    assert result["manifest"]["raw_payload_public"] is False
    for name in result["files"]:
        assert (tmp_path / "public" / name).is_file()


def test_unverified_rdf_cannot_generate_public_navigation(tmp_path):
    from local_server.rdf import generate_rdf, build_navigation
    batch = small_batch(tmp_path)
    generated = generate_rdf(batch, tmp_path / "rdf")
    with pytest.raises(ValueError, match="verified"):
        build_navigation(batch, generated, {"status": "failed"}, tmp_path / "public")


def test_navigation_hash_verification_rejects_tampering_and_path_escape(tmp_path):
    from local_server.rdf import generate_rdf, verify_readback, build_navigation, verify_files
    batch = small_batch(tmp_path)
    generated = generate_rdf(batch, tmp_path / "rdf")
    proof = verify_readback(generated, generated["nt_path"])
    result = build_navigation(batch, generated, proof, tmp_path / "public")
    (tmp_path / "public" / "schema.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        verify_files(tmp_path / "public", result["files"])
    with pytest.raises(ValueError, match="path"):
        verify_files(tmp_path / "public", {"../escape.json": {"bytes": 0, "sha256": "a" * 64}})
