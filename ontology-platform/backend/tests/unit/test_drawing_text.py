"""Protect drawing coverage, spatial identity, and unverified evidence semantics."""
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'extract_drawing_text.py'


def module():
    assert SCRIPT.exists(), 'drawing text extraction implementation is missing'
    spec = importlib.util.spec_from_file_location('drawing_text', SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_tiles_cover_edges_and_overlap_without_oversized_crops():
    tiles = module().make_tiles(5000, 3536)
    assert len(tiles) == 12
    assert tiles[0]['bbox_px'] == [0, 0, 1600, 1600]
    assert tiles[-1]['bbox_px'] == [4440, 2960, 5000, 3536]
    for y in range(0, 3536, 40):
        for x in range(0, 5000, 40):
            assert any(b[0] <= x < b[2] and b[1] <= y < b[3]
                       for b in (t['bbox_px'] for t in tiles))


@pytest.mark.parametrize('size,overlap', [(0, 0), (100, 100), (100, -1)])
def test_bad_tile_configuration_fails_instead_of_hanging(size, overlap):
    with pytest.raises(ValueError):
        module().make_tiles(1000, 1000, size, overlap)


def test_duplicate_text_elsewhere_is_preserved_and_overlap_evidence_retained():
    records = [dict(text_original='400', bbox_px=b, confidence=c, tile_id=t,
                    method='ocr', drawing_id='pdf-01') for b, c, t in [
        ([10, 10, 60, 30], .6, 'a'), ([12, 11, 62, 31], .9, 'b'),
        ([300, 10, 350, 30], .8, 'c')]]
    records.append(dict(records[0], drawing_id='pdf-02'))
    result = module().deduplicate(records)
    assert len(result) == 3
    assert result[0]['confidence'] == .9
    assert len(result[0]['observations']) == 2
    assert result[1]['bbox_px'] == [300, 10, 350, 30]


def test_tile_coordinates_convert_to_paper_without_claiming_ground_units():
    record = module().ocr_record('pdf-01', 't1', [1480, 0, 3080, 1600],
        [[[20, 10], [120, 10], [120, 30], [20, 30]], '12.340', .97],
        [5000, 2500], [1000, 500])
    assert record['bbox_px'] == [1500, 10, 1600, 30]
    assert record['paper_position_pt'] == [310, 4]
    assert record['text_original'] == '12.340'
    assert record['verification_status'] == 'unverified'
    assert record['coordinate_system'] == 'PDF_LANDSCAPE_LOCAL'
    assert record['ground_unit'] is None


def test_failed_tile_does_not_hide_coverage_or_abort_other_tiles(tmp_path):
    from PIL import Image
    image = tmp_path / 'drawing.png'
    Image.new('RGB', (200, 100), 'white').save(image)
    calls = []
    def engine(crop):
        calls.append(crop.shape)
        if len(calls) == 1:
            raise RuntimeError('fixture tile failure')
        return ([[[[1, 1], [20, 1], [20, 10], [1, 10]], '渠', .8]], None)
    result = module().extract_image(image, 'pdf-01', [400, 200], engine, 120, 20)
    assert [t['status'] for t in result['tiles']] == ['failed', 'success']
    assert result['tiles'][0]['error'] == 'RuntimeError: fixture tile failure'
    assert result['coverage']['all_tiles_succeeded'] is False
    assert result['coverage']['semantic_complete'] is False
    assert result['candidates'][0]['bbox_px'] == [101, 1, 120, 10]


def record(box, tile, confidence=.8):
    return dict(text_original='77105.829', bbox_px=box, tile_id=tile,
                confidence=confidence, method='ocr', drawing_id='pdf-03')


@pytest.mark.parametrize('second_tile', ['a', 'b'])
def test_adjacent_same_text_with_slight_overlap_is_not_merged(second_tile):
    rows = [record([303, 175, 353, 192], 'a'),
            record([304, 190, 353, 207], second_tile)]
    assert len(module().deduplicate(rows)) == 2


def test_same_tile_identical_boxes_remain_distinct_observations():
    rows = [record([0, 0, 50, 20], 'a'), record([0, 0, 50, 20], 'a')]
    assert len(module().deduplicate(rows)) == 2


def test_higher_confidence_representative_cannot_bridge_nonmatching_endpoints():
    rows = [record([0, 0, 50, 20], 'a', .7),
            record([6, 0, 56, 20], 'b', .9),
            record([12, 0, 62, 20], 'c', .95)]
    groups = module().deduplicate(rows)
    assert len(groups) == 2
    assert [len(g['observations']) for g in groups] == [2, 1]


def test_rededuplicate_cli_preserves_raw_native_coverage_and_old_group_audit(tmp_path):
    raw = [record([303, 175, 353, 192], 'a'), record([304, 190, 353, 207], 'a')]
    old = [dict(raw[0], observations=raw)]
    drawing = dict(drawing_id='pdf-03', raw_candidates=raw, candidates=old,
                   tiles=[dict(tile_id='a', status='success')], native_candidates=[{'text_original': 'native'}],
                   coverage={'semantic_complete': False})
    source = tmp_path / 'source.json'
    output = tmp_path / 'output.json'
    original = json.dumps({'drawings': [drawing]})
    source.write_text(original, encoding='utf-8')
    assert module().main(['--rededuplicate', str(source), '--output', str(output)]) == 0
    serialized = output.read_text(encoding='utf-8')
    assert serialized.endswith('\n')
    assert '\n' not in serialized[:-1]
    rebuilt = json.loads(output.read_text(encoding='utf-8'))['drawings'][0]
    assert source.read_text(encoding='utf-8') == original
    assert rebuilt['raw_candidates'] == raw
    assert rebuilt['native_candidates'] == drawing['native_candidates']
    assert rebuilt['tiles'] == drawing['tiles']
    assert rebuilt['coverage'] == drawing['coverage']
    assert len(rebuilt['candidates']) == 2
    assert rebuilt['deduplication_audit'][-1]['previous_candidates'] == old
    assert rebuilt['deduplication_audit'][-1]['raw_count'] == 2
