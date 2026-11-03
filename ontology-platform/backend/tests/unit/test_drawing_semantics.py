import copy
import json
from pathlib import Path

from lzo.gis.drawing_semantics import build_semantics, normalize_review_quantity
from lzo.gis.drawing_ontology_import import validate_bundle

DATA = Path(__file__).resolve().parents[3] / 'datasets/drawings'


def build():
    load = lambda name: json.loads((DATA / name).read_text('utf8'))
    return build_semantics(load('package.json'), load('metric-review-12.json'), load('metric-review-345.json'))


def test_scalar_tuple_and_unknown_units_keep_meaning_and_precision():
    result = normalize_review_quantity({'quantity_kind': 'ditch_depth', 'value': 1.1, 'value_original': '1.10', 'unit': 'm'})
    assert result['kind'] == 'channel_depth'
    assert result['value_original'] == '1.10'
    assert result['si_value'] == '1.1'
    triple = normalize_review_quantity({'property': 'dimension_tuple_unassigned_axes', 'value': ['1.5', '1.5', '3'], 'unit': 'm'})
    assert triple['si_value'] is None
    assert triple['components_si'] == ['1.5', '1.5', '3']
    unknown = normalize_review_quantity({'property': 'pink_label_numeric_value_semantics_unknown', 'value': '18.20', 'unit': None})
    assert unknown['kind'] == 'unresolved_field_annotation_number'
    assert unknown['si_value'] is None


def test_all_faces_and_review_quantities_are_connected_to_stable_objects():
    bundle = build()
    validate_bundle(bundle)
    profiles = bundle['profiles']
    assert len(profiles) == 163
    faces = [p for p in profiles if p['kind'] in ('field', 'pond')]
    assert len(faces) == 120
    assert all(p['paper_metrics']['perimeter_pt'] > 0 for p in faces)
    assert all(p['depth']['water_depth_m'] is None for p in faces)
    assert len([m for m in bundle['measurements'] if m['origin'] == 'metric_review']) == 1218
    nodes = {n['id'] for n in bundle['nodes']}
    assert all(m['subject_id'] in nodes and m['id'] in nodes and m['evidence_ids'] for m in bundle['measurements'])
    assert all(e['subject_id'] in nodes and e['object_id'] in nodes for e in bundle['edges'])


def test_bottom_elevation_is_not_pond_depth_and_totals_not_distributed():
    bundle = build()
    bottoms = [m for m in bundle['measurements'] if m['kind'] == 'bottom_elevation' and m['origin'] == 'metric_review']
    assert len(bottoms) == 3
    assert all(m['si_value'] == '17.94' for m in bottoms)
    ponds = {p['entity_id'] for p in bundle['profiles'] if p['kind'] == 'pond'}
    means = [m for m in bundle['measurements'] if m['kind'] == 'project_mean_dredging_thickness']
    assert means and all(m['subject_id'] not in ponds for m in means)
    assert all(m['aggregation_policy'] for m in bundle['measurements'])


def test_deterministic_digest_and_coverage_of_source_rows():
    a, b = build(), build()
    assert a['content_sha256'] == b['content_sha256']
    assert a['coverage']['manual_source_statements'] >= 1000
    assert a['coverage']['semantic_entities_written'] == 0
    assert a['coverage']['ontology_import_status'] == 'requires_governed_import'
    altered = copy.deepcopy(a)
    altered['measurements'][0]['si_value'] = '999'
    import pytest
    with pytest.raises(ValueError, match='digest'):
        validate_bundle(altered)


def test_regions_do_not_merge_by_short_name_and_paper_values_are_numeric():
    bundle=build()
    regions=[n for n in bundle['nodes'] if n['class_iri'].endswith(':Region')]
    assert all(len(n['source_drawing_ids'])==1 for n in regions)
    numeric={n['id'] for n in bundle['nodes'] if any(p['predicate_iri'].endswith(':numericValue') and
              p['term']['datatype_iri'].endswith('#decimal') for p in n['properties'])}
    assert all(m['id'] in numeric for m in bundle['measurements'] if m['origin']=='geometry')
