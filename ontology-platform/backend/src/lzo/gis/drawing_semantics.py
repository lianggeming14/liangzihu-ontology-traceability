"""Deterministic, evidence-linked interpretation of the five construction drawings.

This is an import payload, not proof that the governed ontology accepted it.
Dimensions remain document claims; inferred scales remain explicit scenarios.
"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import UUID, uuid5

from .drawing_metrics import quantity, extract_quantities, geometry_metrics, estimate_ground_metrics

N = 'urn:lzo:drawing-ontology:'
XSD = 'http://www.w3.org/2001/XMLSchema#'
NS = UUID('e17f5efe-d23e-5de2-90bf-953f92abc3e6')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identifier(key):
    return str(uuid5(NS, key))


KINDS = {
    'ditch_depth': 'channel_depth', 'channel_depth_m': 'channel_depth',
    'bottom_elevation_m': 'bottom_elevation', 'spot_elevation_value': 'spot_elevation',
    'derived_mean_dredging_thickness': 'project_mean_dredging_thickness',
    'implied_average_dredging_thickness_m': 'project_mean_dredging_thickness',
    'pink_label_numeric_value_semantics_unknown': 'unresolved_field_annotation_number',
    'labelled_length_m': 'labelled_length', 'labelled_width_m': 'width', 'width_m': 'width',
    'road_width': 'width', 'specified_width': 'width', 'length_m': 'labelled_length',
    'scheduled_length_m': 'linear_work_quantity', 'scheduled_volume_m3': 'earthwork_volume',
    'scheduled_area_m2': 'work_area', 'scheduled_area': 'work_area',
    'scheduled_quantity': 'item_count', 'structure_height_m': 'specified_height',
    'pavement_layer_thickness_m': 'road_layer_thickness',
}


def normalize_review_quantity(record):
    original_kind = record.get('quantity_kind', record.get('property', 'unresolved_quantity'))
    kind = KINDS.get(original_kind, original_kind)
    if kind.startswith('cadastral_area_'):
        kind = 'cadastral_area'
    value = record.get('value')
    original = record.get('value_original', value)
    unit = record.get('unit')
    result = dict(kind=kind, original_kind=original_kind, value=value, value_original=original,
                  unit=unit, si_value=None, si_unit=None)
    if isinstance(value, list):
        components = []
        for entry in value:
            try:
                converted = quantity(entry, unit, kind)
                components.append(converted['si_value'])
                result['si_unit'] = converted['si_unit']
            except ValueError:
                components.append(None)
        result['components_si'] = components
    elif value is not None:
        try:
            converted = quantity(original, unit, kind)
            result.update(si_value=converted['si_value'], si_unit=converted['si_unit'])
        except (ValueError, InvalidOperation):
            pass
    return result


def build_semantics(package, review12, review345, *, version='1'):
    nodes, edges, measurements, profiles = {}, {}, [], []
    manual_count = 0
    features = {f['feature_id']: f for f in package['features']}
    by_entity = {f['entity_id']: f for f in features.values()}
    sheets = {d['drawing_id']: d for d in package['drawings']}
    reviews = {d.get('id', d.get('drawing_id')): d for review in (review12, review345) for d in review['drawings']}
    project = identifier('project:liangzihu-asbuilt-2026-document-collection')

    def node(key, cls, label, drawing_ids=(), *, persistent_id=None):
        uid = persistent_id or identifier(key)
        value = nodes.setdefault(uid, dict(id=uid, class_iri=cls if ':' in cls else N+cls,
            label=str(label)[:512], data_nature='imported_unverified', properties=[], source_drawing_ids=[]))
        value['source_drawing_ids'] = sorted(set(value['source_drawing_ids']) | set(drawing_ids))
        return uid

    def prop(uid, name, value, evidence, datatype='string'):
        if value is None:
            return
        term = {'kind': 'literal', 'value': str(value), 'datatype_iri': XSD+datatype}
        item = dict(predicate_iri=N+name, term=term, evidence_ids=sorted(set(evidence)))
        if item not in nodes[uid]['properties']:
            nodes[uid]['properties'].append(item)

    def edge(subject, name, obj, evidence, derivation):
        key = (subject, name, obj, derivation)
        current = edges.setdefault(key, dict(subject_id=subject, predicate_iri=N+name, object_id=obj,
            evidence_ids=[], derivation=derivation))
        current['evidence_ids'] = sorted(set(current['evidence_ids']) | set(evidence))

    def statement(key, sid, record, category):
        nonlocal manual_count
        uid = node('statement:'+key, 'DocumentStatement', category+' '+key, [sid])
        prop(uid, 'statementCategory', category, [key])
        prop(uid, 'sourceRecord', canonical(record), [key])
        text = record.get('text_original') if isinstance(record, dict) else record
        if text is not None:
            prop(uid, 'sourceText', text if isinstance(text, str) else canonical(text), [key])
        edge(uid, 'depictedIn', identifier('drawing:'+sid), [key], 'statement transcribed from this drawing')
        manual_count += 1
        return uid

    def measurement(key, subject, sid, record, origin, evidence, source_statement=None):
        q = normalize_review_quantity(record)
        uid = node('measurement:'+key, 'Measurement', q['kind']+' '+str(q['value_original'])+' '+str(q['unit'] or ''), [sid])
        status = record.get('verification_status', record.get('status', 'document_claim_not_surveyed'))
        aggregation = record.get('aggregation_policy') or 'Evidence occurrences are not additive; no allocation of project totals to individual objects.'
        item = dict(id=uid, subject_id=subject, drawing_id=sid, origin=origin, **q,
            status=status, source_record=record, evidence_ids=list(evidence), aggregation_policy=aggregation)
        measurements.append(item)
        for name, value in [('quantityKind', q['kind']), ('sourceQuantityKind', q['original_kind']),
            ('valueText', canonical(q['value_original'])), ('unitText', q['unit']), ('siUnit', q['si_unit']),
            ('reviewStatus', status), ('componentLabel', record.get('component_label')),
            ('aggregationPolicy', aggregation), ('sourceRecord', canonical(record))]:
            prop(uid, name, value, evidence)
        if q['si_value'] is not None:
            prop(uid, 'siValue', q['si_value'], evidence, 'decimal')
        # Known paper units and unresolved numeric labels still have numeric
        # values. Decimal storage does not assign them a physical interpretation.
        if not isinstance(q['value_original'], (list,dict)) and q['value_original'] is not None:
            try:
                numeric=Decimal(str(q['value_original']))
                if numeric.is_finite():
                    prop(uid, 'numericValue', format(numeric,'f'), evidence, 'decimal')
            except InvalidOperation:
                pass
        if 'components_si' in q:
            prop(uid, 'componentsSi', canonical(q['components_si']), evidence)
        edge(subject, 'hasMeasurement', uid, evidence, record.get('association_basis') or str(record.get('association_evidence') or 'document subject retained; no inferred physical identity merge'))
        if source_statement:
            edge(uid, 'derivedFromStatement', source_statement, evidence, 'typed interpretation of the exact retained source record')
        return uid

    node('project:liangzihu-asbuilt-2026-document-collection', 'Project', '梁子湖五张竣工图资料集合', sheets)
    prop(project, 'identityScope', 'document collection; not a legal assertion that all five sheets share one contract', ['package:source_manifest'])
    for sid, sheet in sheets.items():
        uid = node('drawing:'+sid, 'SourceDrawing', sheet['label'], [sid])
        prop(uid, 'sourceSha256', sheet['source_sha256'], [sid+':pdf'])
        prop(uid, 'sourcePath', sheet['source_path_on_original_farm'], [sid+':pdf'])
        prop(uid, 'coordinateSystem', 'PDF_LANDSCAPE_LOCAL', [sid+':pdf'])
        edge(uid, 'partOfProject', project, [sid+':pdf'], 'source document in this reviewed collection')

    # Existing farm identities are preserved; label anchors never become unique facilities.
    for f in features.values():
        sid, evidence = f['drawing_id'], [f['feature_id']+':geometry', f['feature_id']+':source']
        cls = f['class_iri'] if f['kind'] in ('field', 'pond') else 'EngineeringAsset' if f['kind'] in ('road', 'channel') else 'DocumentStatement'
        uid = node('feature:'+f['feature_id'], cls, f['label'], [sid], persistent_id=f['entity_id'])
        for name, value in [('representationId', f['feature_id']), ('objectKind', f['kind']),
            ('sourceRecord', canonical(f['source'])), ('identityScope', f['source'].get('identity_scope', 'source representation with persisted farm identity'))]:
            prop(uid, name, value, evidence)
        edge(uid, 'depictedIn', identifier('drawing:'+sid), evidence, 'existing reviewed source representation')
        region = f['source'].get('region')
        if region:
            region_id = node('region:'+sid+':'+region, 'Region', region, [sid])
            edge(uid, 'locatedIn', region_id, evidence, 'region label on original reviewed derivative; not a surveyed administrative boundary')
            edge(region_id, 'partOfProject', project, evidence, 'named region represented in this document collection')
        paper = geometry_metrics(f['geometry'])
        review = reviews[sid]
        c = review.get('calibration', {})
        cal = None
        if c.get('reference_lines') and c.get('point_estimate_m_per_pt'):
            cal = dict(method='reference_length_local_provisional', metres_per_pt=c['point_estimate_m_per_pt'],
                min_metres_per_pt=c['metres_per_pt_interval'][0], max_metres_per_pt=c['metres_per_pt_interval'][1],
                evidence_ids=[sid+':calibration:'+r['representation_id'] for r in c['reference_lines']],
                status='provisional_local_estimate_not_survey', limitations='reference endpoints and uniform sheet scale are unverified; interval excludes tracing error')
        estimate = estimate_ground_metrics(paper, cal)
        scenarios = []
        if f['geometry']['type'] in ('Polygon', 'LineString'):
            for denominator in (1000, 4000):
                scenario = estimate_ground_metrics(paper, dict(method='nominal_scale_scenario', metres_per_pt=denominator*.0254/72,
                    scale_denominator=denominator, evidence_ids=[sid+':title_block_scale'], status='scenario_only_not_adopted'))
                scenarios.append(scenario)
        profile = dict(entity_id=uid, feature_id=f['feature_id'], drawing_id=sid, kind=f['kind'], label=f['label'],
            paper_metrics=paper, ground_estimate=estimate, scale_scenarios=scenarios,
            depth=dict(water_depth_m=None, status='not_reported_for_this_object', required_evidence='individual water level and bed elevation with datum, or verified depth section',
                exclusions=['channel depth', 'bed elevation alone', 'project mean dredging thickness']),
            ledger_area=f['ledger_area'], measurement_ids=[], relations=[], data_nature='imported_unverified',
            calibration_evidence=c or {k: review.get(k) for k in ('scale_evidence', 'calibration_checks')},
            geometry_quality=f['source'].get('boundary_status', f['source'].get('geometry_status')))
        profiles.append(profile)
        for field, kind in [('perimeter_pt', 'paper_perimeter'), ('area_pt2', 'paper_area'), ('length_pt', 'paper_length')]:
            if paper[field] is not None:
                measurement(f['feature_id']+':'+kind, uid, sid, dict(quantity_kind=kind, value=paper[field], unit='pt2' if field=='area_pt2' else 'pt',
                    method=paper['method'], geometry=f['geometry'], status='computed_paper_geometry_not_ground_survey'), 'geometry', evidence)
        if cal:
            for field, kind in [('perimeter_m', 'estimated_perimeter'), ('area_m2', 'estimated_area'), ('length_m', 'estimated_length')]:
                if estimate[field] is not None:
                    measurement(f['feature_id']+':'+kind, uid, sid, dict(quantity_kind=kind, value=estimate[field], unit='m2' if field=='area_m2' else 'm',
                        calibration=estimate, status=estimate['status']), 'calibrated_geometry', evidence+cal['evidence_ids'])
        for scenario in scenarios:
            for field, kind in [('perimeter_m', 'scenario_perimeter'), ('area_m2', 'scenario_area'), ('length_m', 'scenario_length')]:
                if scenario[field] is not None:
                    measurement(f['feature_id']+':'+kind+':'+str(scenario['scale_denominator']), uid, sid,
                        dict(quantity_kind=kind, value=scenario[field], unit='m2' if field=='area_m2' else 'm',
                             scenario=scenario, status='scenario_only_not_adopted'), 'scale_scenario', evidence+scenario['evidence_ids'])
        if f['ledger_area']['value'] is not None:
            measurement(f['feature_id']+':ledger-area', uid, sid, dict(quantity_kind='ledger_area_unit_unconfirmed',
                value=f['ledger_area']['value'], unit=f['ledger_area']['unit'], status='ledger_value_not_ground_area_until_unit_confirmed',
                source_key=f['source'].get('source_key')), 'source_ledger', evidence)

    # Preserve every manually reviewed legend, row, heading and label, not only numeric values.
    manual_annotations = [a for a in package['annotations'] if a['record_type'] not in ('native_text', 'ocr_candidate')
                          and not a['record_type'].startswith('metric_review_')]
    for a in manual_annotations:
        sid, key, category = a['drawing_id'], a['annotation_id'], a['record_type']
        statement_id = statement(key, sid, a, category)
        if category == 'table_row':
            table_id = identifier('statement:'+key.rsplit(':', 1)[0])
            # Table rows always have their parent table in the package.
            edge(statement_id, 'partOfTable', table_id, [key], 'printed table membership')
        # Conservative explicit-unit parsing supplements manually typed review records.
        content = a.get('evidence', a.get('row', {}))
        if isinstance(content, dict):
            text = '；'.join(str(content.get(k, '')) for k in ('label', 'text_original', 'name', 'remark', 'remarks'))
        else:
            text = str(content)
        for i, q in enumerate(extract_quantities(text)):
            before=text[:q['text_span'][0]]
            component_label=re.split(r'[；;、,，（）()]',before)[-1].strip()
            measurement(key+':explicit:'+str(i), statement_id, sid, dict(property=q['quantity_kind'], value=q['value_original'],
                unit=q['unit_original'], text_original=text, token=q, component_label=component_label,
                status=q['status'] if q['quantity_kind']=='count_from_expression' else 'explicit_unit_candidate_requires_context_review'),
                'supplemental_explicit_text', [key], statement_id)
        # Construction totals and cadastral columns carry their unit in the table header.
        if category in ('table', 'table_row'):
            table = a.get('table', {})
            table_unit = table.get('unit') or ('公顷' if '公顷' in str(table.get('unit_original', '')) else None)
            if table_unit:
                def walk(value, path):
                    if isinstance(value, dict):
                        for k, v in value.items():
                            yield from walk(v, path+[k])
                    elif isinstance(value, list):
                        for i, v in enumerate(value):
                            yield from walk(v, path+[str(i)])
                    elif isinstance(value, (int, float, str)) and re.fullmatch(r'\d+\.\d+', str(value)):
                        yield path, value
                roots = {'row': a['row']} if category=='table_row' else {k: table[k] for k in ('merged_cells', 'totals_original', 'totals') if k in table}
                for path, value in walk(roots, []):
                    measurement(key+':cell:'+':'.join(path), statement_id, sid, dict(property='cadastral_table_numeric_cell',
                        value=value, value_original=value, unit=table_unit, column_path=path, table_title=table.get('title'),
                        status='header_unit_applied_to_table_cell_no_field_identity_merge'), 'table_numeric_cell', [key], statement_id)

    # Hand-reviewed quantities use reviewed object associations, never nearest-label guessing.
    target_aliases = {}
    for sid, review in reviews.items():
        for record in review.get('metrics', review.get('assertions', [])):
            target = record.get('target', {})
            representation = record.get('representation_id', target.get('representation_id'))
            key = record.get('metric_id', record.get('assertion_id'))
            scope = record.get('scope', target.get('scope', 'document_subject'))
            label = record.get('object_label', target.get('label', key))
            if representation:
                if representation not in features:
                    raise ValueError('Unknown reviewed representation: '+representation)
                subject = features[representation]['entity_id']
                if features[representation]['drawing_id'] != sid:
                    raise ValueError('Cross-sheet reviewed representation')
            elif scope == 'drawing_sheet':
                subject = identifier('drawing:'+sid)
            else:
                old_id = record.get('object_id', target.get('object_id', key))
                cls = 'EngineeringItem' if 'summary' in scope or 'acceptance-table' in str(old_id) or 'engineering-summary' in str(old_id) or str(old_id).startswith('project:') else 'Region' if scope=='construction_region' else 'EngineeringAsset'
                subject = node('review-subject:'+sid+':'+str(old_id), cls, label, [sid])
                prop(subject, 'identityScope', scope, [key])
                edge(subject, 'depictedIn', identifier('drawing:'+sid), [key], 'document subject; physical uniqueness is not independently verified')
                edge(subject, 'partOfProject', project, [key], 'documentary membership; no allocation of summary quantities')
                target_aliases[(sid, str(old_id))] = subject
            sid_node = statement(key, sid, record, 'metric_review')
            measurement(key, subject, sid, record, 'metric_review', [key], sid_node)
            if normalize_review_quantity(record)['kind']=='project_mean_dredging_thickness' and sid in ('pdf-01','pdf-02'):
                for pond in features.values():
                    match = re.fullmatch(r'清-(\d+)', pond['label'])
                    if pond['kind']=='pond' and pond['drawing_id'] in ('pdf-01','pdf-02') and match and 5<=int(match[1])<=17:
                        edge(pond['entity_id'], 'memberOfReportedWorksGroup', subject, [key,pond['feature_id']+':source'],
                            'explicit 清5—清17 group range and reviewed individual pond labels; total quantities remain on group')
        links = review.get('field_annotation_links', review.get('contained_pink_numeric_candidates', []))
        for i, record in enumerate(links):
            target = record.get('target', {})
            rep = record.get('representation_id', target.get('representation_id'))
            if rep not in features:
                raise ValueError('Unknown contained label representation')
            subject = features[rep]['entity_id']
            key = sid+':contained-label:'+str(i)
            sid_node = statement(key, sid, record, 'contained_field_label')
            edge(subject, 'containsDrawingAnnotation', sid_node, [key], str(record.get('association_basis', record.get('association_evidence'))))
            measurement(key, subject, sid, {**record, 'property':'unresolved_field_annotation_number'}, 'contained_field_label', [key], sid_node)
        for i, check in enumerate(review.get('calibration_checks', [])):
            rep = check.get('representation_id')
            key = sid+':calibration:'+str(i)
            sid_node = statement(key, sid, check, 'calibration_check')
            if rep in features and check.get('labelled_length_m') is not None:
                measurement(key, features[rep]['entity_id'], sid, {**check, 'property':'labelled_length', 'value':check['labelled_length_m'], 'unit':'m',
                    'status':'label_visually_reviewed_endpoints_not_surveyed'}, 'calibration_reference', [key], sid_node)
        # All review limitations/conflicts are part of the graph, not just the final report.
        for category in ('unresolved', 'conflicts'):
            for i, value in enumerate(review.get(category, [])):
                key = sid+':'+category+':'+str(i)
                record = value if isinstance(value, dict) else {'text_original':value}
                statement(key, sid, record, category)

    # Link repeated evidence, retaining conflicts and occurrence IDs separately.
    duplicates = defaultdict(list)
    for item in measurements:
        record = item['source_record']
        group = record.get('duplicate_evidence_group')
        if group:
            duplicates[(group,item['original_kind'],canonical(item['value_original']),str(item['unit']))].append(item)
    for occurrences in duplicates.values():
        anchor = min(occurrences, key=lambda m:m['id'])
        for item in occurrences:
            if item is not anchor:
                edge(item['id'], 'repeatsReportedQuantity', anchor['id'], item['evidence_ids']+anchor['evidence_ids'],
                     'explicit repeated project table group, same quantity kind/value/unit; not an additive new measurement')

    grouped = defaultdict(list)
    for item in measurements:
        grouped[item['subject_id']].append(item['id'])
    outgoing = defaultdict(list)
    for item in edges.values():
        outgoing[item['subject_id']].append(item)
    for profile in profiles:
        profile['measurement_ids'] = sorted(grouped[profile['entity_id']])
        profile['relations'] = sorted(outgoing[profile['entity_id']], key=canonical)
    result = dict(schema_version='drawing-semantics/1', dataset_id=package['dataset_id'], version=str(version),
        source_package_sha256=package['content_sha256'], source_package_version=package['version'],
        drawings=[dict(id=sid, source_sha256=d['source_sha256'], source_path=d['source_path_on_original_farm']) for sid,d in sorted(sheets.items())],
        nodes=sorted(nodes.values(), key=lambda n:n['id']), edges=sorted(edges.values(), key=canonical),
        measurements=sorted(measurements, key=lambda m:m['id']), profiles=sorted(profiles, key=lambda p:p['feature_id']),
        coverage=dict(manual_source_statements=manual_count, entities_by_class=dict(Counter(n['class_iri'] for n in nodes.values())),
            measurements_by_kind=dict(Counter(m['kind'] for m in measurements)), measurements_by_origin=dict(Counter(m['origin'] for m in measurements)),
            polygon_perimeters=sum(p['paper_metrics']['perimeter_pt'] is not None for p in profiles),
            metric_perimeters_provisionally_calibrated=sum(p['ground_estimate']['perimeter_m'] is not None for p in profiles),
            pond_water_depths_reported=0, semantic_entities_written=0, ontology_import_status='requires_governed_import',
            data_nature='imported_unverified', source_completeness='manual evidence and complete OCR retained; unresolved labels and unvectorized background remain explicit',
            duplicate_policy='occurrences retained independently; project table repeats are not additive; no per-pond allocation',
            source_ocr_annotations_retained_in_gis=sum(a['record_type']=='ocr_candidate' for a in package['annotations'])))
    for value in result['nodes']:
        value['properties'].sort(key=canonical)
    result['content_sha256'] = hashlib.sha256(canonical(result).encode('utf8')).hexdigest()
    return result
