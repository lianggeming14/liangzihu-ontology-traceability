"""Drawing import contracts: persistent identity and no promotion of source claims."""
import copy
import hashlib
import importlib
import importlib.util
import json
from uuid import UUID

import pytest

N = 'urn:lzo:drawing-ontology:'
A = 'aa59ad24-365a-45e7-8496-12653e19d701'
B = 'b2cbd512-456f-4333-a0df-7a3146a0d3ed'


def seal(value):
    value = copy.deepcopy(value)
    value.pop('content_sha256', None)
    value['content_sha256'] = hashlib.sha256(json.dumps(value, ensure_ascii=False,
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return value


def bundle():
    return seal({'schema_version': 'drawing-semantics/1', 'dataset_id': 'farm-drawings',
        'version': '1', 'drawings': [{'id': 'pdf-01', 'source_sha256': 'a' * 64,
            'source_path': 'drawings/one.pdf'}], 'nodes': [
        {'id': A, 'class_iri': N + 'DocumentStatement', 'label': '图纸记载面积',
         'data_nature': 'imported_unverified', 'source_drawing_ids': ['pdf-01'],
         'properties': [{'predicate_iri': N + 'statedArea',
             'term': {'kind': 'literal', 'value': '12.50',
                      'datatype_iri': 'http://www.w3.org/2001/XMLSchema#decimal'},
             'evidence_ids': ['pdf-01:table:01:0001']}]},
        {'id': B, 'class_iri': 'https://w3id.org/lzo/ontology/Pond', 'label': '塘一',
         'data_nature': 'imported_unverified', 'source_drawing_ids': ['pdf-01'],
         'properties': []}], 'edges': [{'subject_id': A, 'predicate_iri': N + 'about',
             'object_id': B, 'evidence_ids': ['pdf-01:table:01:0001'],
             'derivation': 'manual_transcription_not_survey'}]})


@pytest.fixture
def importer():
    name = 'lzo.gis.drawing_ontology_import'
    assert importlib.util.find_spec(name) is not None, 'Formal drawing ontology importer is missing'
    return importlib.import_module(name)


def test_formal_importer_is_available():
    assert importlib.util.find_spec('lzo.gis.drawing_ontology_import') is not None


def test_document_statement_value_remains_candidate_with_stable_farm_identity(importer):
    plan = importer.build_plan(bundle())
    assert plan['objects'][0]['resource_id'] == A
    assert plan['objects'][0]['class_iris'] == [N + 'DocumentStatement']
    assert plan['objects'][0]['data_nature'] == 'imported_unverified'
    source = [a for a in plan['assertions'] if a['predicate_iri'] == N + 'statedArea'][0]
    assert source['state'] == 'candidate'
    assert source['object']['value'] == '12.50'
    assert source['evidence_ids'] == ['pdf-01:table:01:0001']
    relation = [a for a in plan['assertions'] if a['predicate_iri'] == N + 'about'][0]
    assert relation['state'] == 'candidate' and relation['object']['value'] == 'urn:lzo:object:' + B
    accepted = [a for a in plan['assertions'] if a['state'] == 'accepted']
    assert len(accepted) == 6
    assert all(a['predicate_iri'] in {N + 'importDataset', N + 'importVersion', N + 'importBundleSha256'} for a in accepted)


def test_plan_is_repeatable_and_assertions_are_not_reidentified_on_reorder(importer):
    first = bundle()
    second = copy.deepcopy(first)
    second['nodes'].reverse()
    second = seal(second)
    left, right = importer.build_plan(first), importer.build_plan(second)
    source_left = {a['assertion_id'] for a in left['assertions'] if a['state'] == 'candidate'}
    source_right = {a['assertion_id'] for a in right['assertions'] if a['state'] == 'candidate'}
    assert source_left == source_right
    assert len(source_left) == 2
    assert all(str(UUID(value)) == value for value in source_left)
    assert importer.build_plan(first) == left


@pytest.mark.parametrize('mutation', ['hash', 'nature', 'dangling', 'duplicate', 'missing_drawing', 'path_escape', 'term'])
def test_bad_input_cannot_reach_any_write(importer, mutation):
    value = bundle()
    if mutation == 'hash': value['nodes'][0]['label'] = 'changed'
    elif mutation == 'nature': value['nodes'][0]['data_nature'] = 'verified'
    elif mutation == 'dangling': value['edges'][0]['object_id'] = '875be2ec-2dca-4f58-bf0b-949565195b88'
    elif mutation == 'duplicate': value['nodes'].append(copy.deepcopy(value['nodes'][0]))
    elif mutation == 'missing_drawing': value['nodes'][0]['source_drawing_ids'] = ['missing']
    elif mutation == 'path_escape': value['drawings'][0]['source_path'] = '../one.pdf'
    elif mutation == 'term': value['nodes'][0]['properties'][0]['term']['kind'] = 'blank'
    if mutation != 'hash': value = seal(value)
    with pytest.raises(ValueError): importer.build_plan(value)


def test_resume_identity_cannot_cross_payload_operator_or_scope(importer):
    value = bundle()
    scope = UUID('c91c436f-a202-465b-aa08-55cff031c84e')
    actor = UUID('52e630f4-3825-46b8-9af8-e6953761d83d')
    first = importer.command_identity(value, actor, scope)
    assert first == importer.command_identity(value, actor, scope)
    changed = seal({**value, 'nodes': [dict(value['nodes'][0], label='new'), value['nodes'][1]]})
    assert importer.command_identity(changed, actor, scope)['key'] == first['key']
    assert importer.command_identity(changed, actor, scope)['digest'] != first['digest']
    assert importer.command_identity(value, UUID(A), scope)['key'] == first['key']
    assert importer.command_identity(value, UUID(A), scope)['digest'] != first['digest']
    assert importer.command_identity(value, actor, UUID(B))['digest'] != first['digest']


def test_resume_skips_exact_live_support_but_rejects_tampered_or_withdrawn(importer):
    planned = importer.build_plan(bundle())['assertions'][0]
    assert importer.pending_assertions([planned], {}) == [planned]
    persisted = {planned['assertion_id']: {'assertion': copy.deepcopy(planned), 'active': True}}
    assert importer.pending_assertions([planned], persisted) == []
    persisted[planned['assertion_id']]['assertion']['object']['value'] = 'tampered'
    with pytest.raises(ValueError, match='conflict'): importer.pending_assertions([planned], persisted)
    persisted[planned['assertion_id']] = {'assertion': copy.deepcopy(planned), 'active': False}
    with pytest.raises(ValueError, match='withdrawn'): importer.pending_assertions([planned], persisted)


def test_schema_extension_preserves_constraints_and_uses_writable_authority(importer):
    from lzo.ontology.schemas import SchemaDocument, ClassDef, PropertyDef
    original = SchemaDocument(classes=(ClassDef(iri='urn:existing:Class', label='Kept'),),
        properties=(PropertyDef(iri='urn:existing:readonly', label='Locked',
            datatype_iri='http://www.w3.org/2001/XMLSchema#string',
            owner_policy_iri='urn:lzo:authority:read_only'),),
        shapes='@prefix sh: <http://www.w3.org/ns/shacl#> .', ui_metadata={'existing': 'retained'})
    extended = importer.extend_document(original, importer.build_plan(bundle()))
    assert extended.classes[0] == original.classes[0]
    assert extended.properties[0] == original.properties[0]
    assert extended.shapes == original.shapes and extended.ui_metadata == original.ui_metadata
    assert all(p.owner_policy_iri == 'urn:lzo:authority:ontology_owned' for p in extended.properties[1:])
    assert importer.extend_document(extended, importer.build_plan(bundle())) == extended


def test_original_hash_and_symlink_confinement_precede_write(importer, tmp_path):
    value = bundle()
    (tmp_path / 'drawings').mkdir()
    original = tmp_path / 'drawings/one.pdf'
    original.write_bytes(b'actual drawing bytes')
    value['drawings'][0]['source_sha256'] = hashlib.sha256(b'actual drawing bytes').hexdigest()
    plan = importer.build_plan(seal(value))
    assert importer.verify_originals(plan, tmp_path)['pdf-01'] == original
    original.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'): importer.verify_originals(plan, tmp_path)


def test_property_object_iris_must_resolve_before_any_write(importer):
    value = bundle()
    value['nodes'][0]['properties'][0]['term'] = {'kind': 'iri',
        'value': 'urn:lzo:object:875be2ec-2dca-4f58-bf0b-949565195b88'}
    with pytest.raises(ValueError, match='endpoint'):
        importer.build_plan(seal(value))


def test_source_version_is_original_hash_while_snapshot_is_derived_bundle(importer):
    from datetime import datetime, timezone
    fact = importer.build_plan(bundle())['assertions'][0]
    def evidence(identifier, sha):
        return {'source_id': identifier, 'evidence': {
            'revision': {'resource_id': identifier, 'revision': 1, 'event_id': identifier},
            'blob': {'sha256': sha, 'size_bytes': 100, 'media_type': 'application/pdf', 'version_id': identifier}}}
    values = {'bundle': evidence(A, 'b' * 64), 'pdf-01': evidence(B, 'c' * 64)}
    instance = importer.GovernedDrawingImport.__new__(importer.GovernedDrawingImport)
    result = instance._input(fact, values, datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert result.support.source_id == UUID(B)
    assert result.support.source_version == 'c' * 64
    assert result.support.snapshot.sha256 == 'b' * 64


def test_edge_evidence_from_another_drawing_pins_its_actual_original(importer):
    value = bundle()
    value['drawings'].append({'id': 'pdf-02', 'source_sha256': 'd' * 64, 'source_path': 'drawings/two.pdf'})
    value['edges'][0]['evidence_ids'] = ['pdf-02:table:01:0001']
    edge = next(a for a in importer.build_plan(seal(value))['assertions'] if a['predicate_iri'] == N + 'about')
    assert 'pdf-02' in edge['source_drawing_ids']
    assert edge['primary_source'] == 'pdf-02'


def test_unknown_edge_locator_uses_bundle_derivation_instead_of_guessing_pdf(importer):
    value = bundle()
    value['edges'][0]['evidence_ids'] = ['metric-review-12:item:31']
    edge = next(a for a in importer.build_plan(seal(value))['assertions'] if a['predicate_iri'] == N + 'about')
    assert edge['primary_source'] == 'bundle'


def test_cli_builds_reviewable_schema_without_database_or_actor(tmp_path, capsys):
    from pathlib import Path
    script = Path(__file__).resolve().parents[3] / 'scripts/import_drawing_ontology.py'
    spec = importlib.util.spec_from_file_location('drawing_import_cli_test', script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    source = tmp_path / 'bundle.json'
    source.write_text(json.dumps(bundle()), encoding='utf8')
    output = tmp_path / 'schema.json'
    assert cli.main(['--bundle', str(source), '--schema-document', str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    schema = json.loads(output.read_text('utf8'))
    assert report['database_written'] is False
    assert report['schema_review']['impact_status'] == 'offline_not_executed'
    assert report['schema_review']['independent_approval_required'] is True
    assert {c['iri'] for c in schema['classes']} == {N + 'DocumentStatement', 'https://w3id.org/lzo/ontology/Pond'}
    assert len(schema['relations']) == 1 and len(schema['properties']) == 4


def test_worker_drain_accounts_for_budget_and_stops_when_idle(importer, monkeypatch):
    from types import SimpleNamespace
    from lzo.worker import runner
    work = iter((True, True, False))
    monkeypatch.setattr(runner, 'Runner', lambda *args: SimpleNamespace(run_once=lambda: next(work)))
    service = importer.GovernedDrawingImport.__new__(importer.GovernedDrawingImport)
    service.engine = None
    service.settings = SimpleNamespace(storage_mode='legacy')
    assert service.drain(20) == 3
    assert service.drain(0) == 0
