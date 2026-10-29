"""Read-only tiled OCR evidence extraction; no OCR imports until main runs.

Run with rapidocr_onnxruntime==1.4.4, Pillow and numpy installed. Confidence
is an engine score, never factual accuracy. Paper coordinates are not metres.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path


def make_tiles(width, height, tile_size=1600, overlap=120):
    if min(width, height, tile_size) <= 0 or not 0 <= overlap < tile_size:
        raise ValueError('positive dimensions and 0 <= overlap < tile_size required')
    step = tile_size - overlap
    return [{'tile_id': f'r{row:03d}-c{col:03d}',
             'bbox_px': [x, y, min(x + tile_size, width), min(y + tile_size, height)]}
            for row, y in enumerate(range(0, height, step))
            for col, x in enumerate(range(0, width, step))]


def ocr_record(drawing_id, tile_id, tile_bbox, result, image_size, page_size):
    polygon, text, score = result
    points = [[float(p[0]) + tile_bbox[0], float(p[1]) + tile_bbox[1]] for p in polygon]
    if not points or not all(math.isfinite(v) for p in points for v in p):
        raise ValueError('invalid OCR polygon')
    bbox = [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]
    sx, sy = page_size[0] / image_size[0], page_size[1] / image_size[1]
    return {'drawing_id': drawing_id, 'text_original': str(text),
            'confidence': float(score), 'confidence_semantics': 'engine_score_not_truth_probability',
            'bbox_px': bbox, 'polygon_px': points,
            'paper_bbox_pt': [bbox[0]*sx, bbox[1]*sy, bbox[2]*sx, bbox[3]*sy],
            'paper_position_pt': [(bbox[0]+bbox[2])*sx/2, (bbox[1]+bbox[3])*sy/2],
            'tile_id': tile_id, 'method': 'rapidocr_onnxruntime/1.4.4',
            'verification_status': 'unverified', 'coordinate_system': 'PDF_LANDSCAPE_LOCAL',
            'coordinate_origin': 'top_left', 'ground_unit': None, 'georeferenced': False}


def deduplicate(records, center_tolerance_px=8):
    """Merge only matching cross-tile observations of the same text instance.

    Require IoU >= .7, centers within eight pixels and each side within 25%.
    Every member must match every other member; representative replacement must
    never create a transitive chain. Same-tile observations always remain apart.
    """
    def matches(first, second):
        if first.get('tile_id') is None or second.get('tile_id') is None:
            return False
        if first['tile_id'] == second['tile_id']:
            return False
        a, b = first['bbox_px'], second['bbox_px']
        aw, ah, bw, bh = a[2]-a[0], a[3]-a[1], b[2]-b[0], b[3]-b[1]
        if min(aw, ah, bw, bh) <= 0:
            return False
        if max(aw, bw)/min(aw, bw) > 1.25 or max(ah, bh)/min(ah, bh) > 1.25:
            return False
        intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
        iou = intersection / (aw*ah + bw*bh - intersection)
        distance = math.hypot((a[0]+a[2]-b[0]-b[2])/2, (a[1]+a[3]-b[1]-b[3])/2)
        return iou >= .7 and distance <= center_tolerance_px

    groups = []
    for record in records:
        match = None
        for group in groups:
            if (group['drawing_id'], group['text_original'], group['method']) != (
                    record['drawing_id'], record['text_original'], record['method']):
                continue
            if all(matches(record, observation) for observation in group['observations']):
                match = group
                break
        if match is None:
            group = copy.deepcopy(record)
            group['observations'] = [copy.deepcopy(record)]
            groups.append(group)
        else:
            observations = match['observations']
            observations.append(copy.deepcopy(record))
            if record.get('confidence', 0) > match.get('confidence', 0):
                match.update(copy.deepcopy(record))
            match['observations'] = observations
    return groups


def rededuplicate(package):
    """Rebuild from immutable raw evidence and retain the prior grouping audit."""
    result = copy.deepcopy(package)
    for drawing in result['drawings']:
        raw = drawing['raw_candidates']
        rebuilt = deduplicate(raw)
        drawing.setdefault('deduplication_audit', []).append({
            'method': 'cross_tile_all_pairs_iou_v2',
            'criteria': {'iou_min': .7, 'center_distance_max_px': 8,
                         'side_length_ratio_max': 1.25, 'same_tile_merge': False,
                         'all_observations_must_match': True},
            'raw_count': len(raw), 'previous_count': len(drawing['candidates']),
            'new_count': len(rebuilt), 'previous_candidates': drawing['candidates'],
            'raw_sha256': hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=True,
                                                   separators=(',', ':')).encode()).hexdigest()})
        drawing['candidates'] = rebuilt
    return result


def extract_image(path, drawing_id, page_size, engine, tile_size=1600, overlap=120):
    from PIL import Image
    import numpy as np
    candidates = []
    with Image.open(path) as source:
        image_size = list(source.size)
        tiles = make_tiles(*source.size, tile_size, overlap)
        for tile in tiles:
            tile.update(status='pending', error=None, candidate_count=0, candidate_errors=[])
            try:
                crop = np.asarray(source.crop(tile['bbox_px']).convert('RGB'))[:, :, ::-1].copy()
                results, _ = engine(crop)
                for index, result in enumerate(results or []):
                    try:
                        candidates.append(ocr_record(drawing_id, tile['tile_id'], tile['bbox_px'],
                                                     result, image_size, page_size))
                        tile['candidate_count'] += 1
                    except Exception as exc:
                        tile['candidate_errors'].append({'index': index, 'error': f'{type(exc).__name__}: {exc}',
                                                         'raw_result': repr(result)})
                tile['status'] = 'partial' if tile['candidate_errors'] else 'success'
            except Exception as exc:
                tile.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    return {'drawing_id': drawing_id, 'image_size_px': image_size, 'page_size_pt': page_size,
            'image_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(), 'tiles': tiles,
            'raw_candidates': candidates, 'candidates': deduplicate(candidates),
            'coverage': {'all_tiles_succeeded': all(t['status'] == 'success' for t in tiles),
                         'planned_tiles': len(tiles), 'attempted_tiles': len(tiles),
                         'semantic_complete': False, 'note': 'Tile coverage is not proof of complete text recognition.'}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--farm-root', type=Path)
    mode.add_argument('--rededuplicate', type=Path,
                      help='Rebuild saved raw candidates without importing or running OCR')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tile-size', type=int, default=1600)
    parser.add_argument('--overlap', type=int, default=120)
    args = parser.parse_args(argv)
    if args.rededuplicate:
        package = json.loads(args.rededuplicate.read_text(encoding='utf-8'))
        rebuilt = rededuplicate(package)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rebuilt, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8',newline='\n')
        for drawing in rebuilt['drawings']:
            audit = drawing['deduplication_audit'][-1]
            print(f'{drawing["drawing_id"]}: {audit["previous_count"]} -> {audit["new_count"]}; raw={audit["raw_count"]}', flush=True)
        return 0
    farm = args.farm_root.resolve()
    output = args.output.resolve()
    if output == farm or farm in output.parents:
        parser.error('--output must not write into farm-root')
    make_tiles(1, 1, args.tile_size, args.overlap)
    metadata = json.loads((farm / 'data/spatial/drawing-entities.json').read_text(encoding='utf-8'))
    native = json.loads((farm / 'data/spatial/native-annotations.json').read_text(encoding='utf-8'))
    from rapidocr_onnxruntime import RapidOCR
    # Avoid shrinking a 1600px tile to the usual 736px detector input.
    engine = RapidOCR(det_limit_side_len=args.tile_size, det_limit_type='max')
    package = {'schema_version': 'drawing-text-candidates/1', 'drawings': [],
               'verification_status': 'unverified', 'semantic_complete': False,
               'coordinate_policy': 'Paper/image coordinates only; no ground unit or CRS inferred.',
               'ocr_settings': {'tile_size': args.tile_size, 'overlap': args.overlap,
                                'engine': 'rapidocr_onnxruntime==1.4.4'},
               'native_method': 'verbatim_import_of_existing_pdf_native_annotations',
               'native_completeness': 'all_existing_records_preserved; PDF outline glyphs require OCR'}
    for number in range(1, 6):
        drawing_id = f'pdf-{number:02d}'
        relative = f'data/spatial/drawings/{drawing_id}-landscape.png'
        drawing_metadata = next((d for d in metadata['drawings'] if d['image_path'] == relative), None)
        try:
            if not drawing_metadata:
                raise ValueError('Missing page size metadata; refusing to infer paper scale')
            result = extract_image(farm / relative, drawing_id, drawing_metadata['page_size_pt'],
                                   engine, args.tile_size, args.overlap)
        except Exception as exc:
            result = {'drawing_id': drawing_id, 'tiles': [], 'candidates': [], 'raw_candidates': [],
                      'error': f'{type(exc).__name__}: {exc}',
                      'coverage': {'semantic_complete': False, 'all_tiles_succeeded': False}}
        native_rows = []
        for item in native:
            if item.get('slug') == drawing_id:
                for index, annotation in enumerate(item['annotations']):
                    native_rows.append({'native_record_index': index, 'text_original': annotation['text'],
                        'method': 'existing_pdf_native_annotation', 'confidence': None,
                        'verification_status': 'unverified', 'paper_position_pt': annotation.get('page_point_pt'),
                        'coordinate_system': 'SOURCE_NATIVE_PDF_PAGE_UNTRANSFORMED',
                        'bbox_px': None, 'tile_id': None, 'original_annotation': annotation,
                        'source_file': item.get('source_file'), 'source_page': item.get('page'),
                        'note': 'Original native positions retained; not mixed with landscape OCR until transform verified.'})
        result['native_candidates'] = native_rows
        result['source_image'] = relative
        result['source_pdf'] = drawing_metadata.get('source_file') if drawing_metadata else None
        package['drawings'].append(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(package, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8',newline='\n')
        print(f'{drawing_id}: {len(result["candidates"])} spatial text candidates, '
              f'{len(native_rows)} native records, tiles={len(result["tiles"])}', flush=True)
    return 0 if all(d['coverage']['all_tiles_succeeded'] for d in package['drawings']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
