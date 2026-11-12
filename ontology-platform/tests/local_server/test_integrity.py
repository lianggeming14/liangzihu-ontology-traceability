import gzip
from pathlib import Path

import pytest

from local_server.integrity import IntegrityError, rdf_dataset_digest, sha256_file


def write_nq(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


def test_dataset_digest_preserves_lexical_datatypes_default_and_named_graphs(tmp_path):
    first = write_nq(tmp_path, 'one.nq', '<urn:s> <urn:p> "01"^^<http://www.w3.org/2001/XMLSchema#integer> .\n<urn:s> <urn:p> "one" <urn:g> .\n')
    second = write_nq(tmp_path, 'two.nq', '<urn:s> <urn:p> "one" <urn:g> .\n<urn:s> <urn:p> "01"^^<http://www.w3.org/2001/XMLSchema#integer> .\n')
    changed = write_nq(tmp_path, 'changed.nq', '<urn:s> <urn:p> "1"^^<http://www.w3.org/2001/XMLSchema#integer> .\n<urn:s> <urn:p> "one" <urn:g> .\n')
    digest = rdf_dataset_digest(first)
    assert digest['dataset_sha256'] == rdf_dataset_digest(second)['dataset_sha256']
    assert digest['dataset_sha256'] != rdf_dataset_digest(changed)['dataset_sha256']
    assert digest['quad_count'] == 2
    assert digest['default_graph_quad_count'] == 1
    assert digest['named_graphs'] == [{'graph': '<urn:g>', 'quad_count': 1}]


def test_blank_nodes_are_compared_across_the_whole_dataset(tmp_path):
    first = write_nq(tmp_path, 'one.nq', '_:a <urn:p> "01"^^<urn:integer> <urn:g1> .\n_:a <urn:next> _:b <urn:g2> .\n_:b <urn:p> "tail" .\n')
    renamed = write_nq(tmp_path, 'two.nq', '_:x <urn:next> _:z <urn:g2> .\n_:z <urn:p> "tail" .\n_:x <urn:p> "01"^^<urn:integer> <urn:g1> .\n')
    disconnected = write_nq(tmp_path, 'three.nq', '_:x <urn:next> _:z <urn:g2> .\n_:z <urn:p> "tail" .\n_:other <urn:p> "01"^^<urn:integer> <urn:g1> .\n')
    assert rdf_dataset_digest(first)['dataset_sha256'] == rdf_dataset_digest(renamed)['dataset_sha256']
    assert rdf_dataset_digest(first)['dataset_sha256'] != rdf_dataset_digest(disconnected)['dataset_sha256']


def test_symmetric_blank_nodes_and_gzip_are_verified_without_lexical_normalization(tmp_path):
    first = write_nq(tmp_path, 'one.nq', '_:a <urn:p> _:b <urn:g> .\n_:b <urn:p> _:a <urn:g> .\n')
    compressed = tmp_path / 'two.nq.gz'
    with gzip.open(compressed, 'wt', encoding='utf-8') as out:
        out.write('_:y <urn:p> _:x <urn:g> .\n_:x <urn:p> _:y <urn:g> .\n')
    assert rdf_dataset_digest(first)['dataset_sha256'] == rdf_dataset_digest(compressed)['dataset_sha256']
    assert sha256_file(compressed)['size_bytes'] == compressed.stat().st_size


@pytest.mark.parametrize('text', ['<urn:s> <urn:p> "unterminated .\n', '<< <urn:s> <urn:p> <urn:o> >> <urn:p> <urn:o> .\n'])
def test_invalid_or_unsupported_rdf_is_refused(tmp_path, text):
    with pytest.raises(IntegrityError):
        rdf_dataset_digest(write_nq(tmp_path, 'invalid.nq', text))


def test_ambiguous_blank_node_work_is_bounded_and_never_marked_verified(tmp_path):
    text = ''.join(f'_:b{i} <urn:p> _:b{(i + 1) % 10} .\n' for i in range(10))
    with pytest.raises(IntegrityError, match='BLANK_NODE'):
        rdf_dataset_digest(write_nq(tmp_path, 'ambiguous.nq', text), max_blank_permutations=100)


def test_excess_graph_metadata_is_bounded(tmp_path):
    path = write_nq(tmp_path, 'graphs.nq', '<urn:s> <urn:p> "a" <urn:g1> .\n<urn:s> <urn:p> "b" <urn:g2> .\n')
    with pytest.raises(IntegrityError, match='GRAPH'):
        rdf_dataset_digest(path, max_named_graphs=1)


def test_rdf_escape_syntax_is_compared_as_the_same_lexical_value(tmp_path):
    escaped = write_nq(tmp_path, 'escaped.nq', '<urn:s> <urn:p> "caf\\u00e9"@EN .\n')
    unicode = write_nq(tmp_path, 'unicode.nq', '<urn:s> <urn:p> "café"@en .\n')
    assert rdf_dataset_digest(escaped)['dataset_sha256'] == rdf_dataset_digest(unicode)['dataset_sha256']


def test_disk_partitioned_digest_merges_every_quad_and_ignores_export_order(tmp_path):
    lines = [f'<urn:s{i}> <urn:p> "value{i}" <urn:g> .\n' for i in range(13)]
    forward = write_nq(tmp_path, 'forward.nq', ''.join(lines))
    reverse = write_nq(tmp_path, 'reverse.nq', ''.join(reversed(lines)))
    changed = write_nq(tmp_path, 'changed.nq', ''.join(lines[:-1]))
    result = rdf_dataset_digest(forward, max_chunk_quads=2, max_open_chunks=2)
    assert result['quad_count'] == 13
    assert result['dataset_sha256'] == rdf_dataset_digest(reverse, max_chunk_quads=3, max_open_chunks=2)['dataset_sha256']
    assert result['dataset_sha256'] != rdf_dataset_digest(changed, max_chunk_quads=2, max_open_chunks=2)['dataset_sha256']
