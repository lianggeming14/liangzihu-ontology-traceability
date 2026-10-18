"""Synthetic source records only. Each case runs on an isolated backend/schema."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import hashlib

import pytest

from agri.service import DomainError, _json
from agri.source_mapping import SourceMappingService

TENANT = 'source-test'
ACTOR = {'id':'source-administrator','tenant_id':TENANT,'roles':['ontology_admin']}
START = '2025-01-01T00:00:00Z'
LATER = '2025-01-02T00:00:00Z'
THIRD = '2025-01-03T00:00:00Z'
PARENT, CHILD = str(uuid4()), str(uuid4())


def package():
    return {'package_id':'test.source','version':'1.0.0','namespace':'urn:test:source:',
            'types':[{'type_id':'source:Place','identity_type':'source_place','label':'来源场所'}],
            'properties':[
                {'property_id':'place.name','applies_to':['source:Place'],'label':'名称','usage':'attribute','value_type':'string','required':True},
                {'property_id':'place.area','applies_to':['source:Place'],'label':'面积','usage':'attribute','value_type':'decimal','unit':'ha','minimum':0},
                {'property_id':'place.at','applies_to':['source:Place'],'label':'源时刻','usage':'attribute','value_type':'datetime'},
                {'property_id':'place.date','applies_to':['source:Place'],'label':'源日期','usage':'attribute','value_type':'string'},
                {'property_id':'place.labels','applies_to':['source:Place'],'label':'标签','usage':'attribute','value_type':'string','cardinality':'many'},
                {'property_id':'place.count','applies_to':['source:Place'],'label':'计数','usage':'attribute','value_type':'integer'},
            ],
            'predicates':[{'predicate_id':'source:parent','label':'父场所','subject_types':['source_place'],
                           'object_types':['source_place'],'dimension':'spatial','irreflexive':True}]}


def profile():
    return {'source_id':'external-farm','profile_id':'test-profile','version':'1.0.0','tables':[
        {'table':'places','primary_key':['id'],'key_types':{'id':'uuid'},
         'type_ref':{'package_id':'test.source','version':'1.0.0','type_id':'source:Place'},
         'name_field':'label','fields':[
             {'source_field':'label','property_id':'place.name'},
             {'source_field':'area','property_id':'place.area','transform':'decimal','source_unit':'ha'},
             {'source_field':'at','property_id':'place.at','transform':'datetime'},
             {'source_field':'date','property_id':'place.date','transform':'date'},
             {'source_field':'labels','property_id':'place.labels','transform':'text_array'},
             {'source_field':'count','property_id':'place.count','transform':'integer'},
         ],
         'relations':[{'relation_key':'parent','fields':['parent_id'],'target_table':'places','target_fields':['id'],
                       'predicate_ref':{'package_id':'test.source','version':'1.0.0','predicate_id':'source:parent'},'nullable':True}],
         'deferred_fields':[{'field':'geometry','reason':'等待显式空间坐标映射'}],
         'rejected_fields':['password','token']} ]}


@pytest.fixture()
def env(database):
    service = SourceMappingService(database)
    service.mutate('install_source_bundle',TENANT,ACTOR,{'packages':[package()],'profile':profile()},'install')
    return service


def write(service,action,p,key=None,tenant=TENANT,actor=ACTOR):
    return service.mutate(action,tenant,actor,p,key or str(uuid4()))


def batch(records=None,at=START,batch_id=None):
    return {'source_id':'external-farm','profile_id':'test-profile','version':'1.0.0',
            'batch_id':batch_id or str(uuid4()),'observed_at':at,'data_nature':'synthetic',
            'records':records or [{'table':'places','values':{'id':PARENT,'label':'合成场所','area':'1.234567890123456789'}}]}


def number(service,table):
    with service.db.transaction() as tx:
        return int(tx.execute('SELECT COUNT(*) AS n FROM '+table).fetchone()['n'])


def detail(service,binding_id):
    return service.query('source_bindings',TENANT,ACTOR,{'binding_id':binding_id})['items'][0]


def inner_code(exc):
    value = exc.value
    return value.details[0]['code'] if value.code == 'source_batch_validation_failed' else value.code


def test_system_uuid_exact_source_binding_and_immutable_receipt(env):
    payload = batch()
    first = write(env,'import_source_batch',payload)
    row = first['records'][0]
    assert row['entity_key'] != PARENT and row['revision'] == 1
    assert first['counts'] == {'created':1,'updated':0,'unchanged':0,'relations_created':0,'relations_closed':0}
    assert write(env,'import_source_batch',payload) == first
    again = write(env,'import_source_batch',dict(payload,batch_id='another'))
    assert again['counts']['unchanged'] == 1 and again['records'][0]['entity_key'] == row['entity_key']
    assert number(env,'entities') == 1 and number(env,'evidence') == 1
    item = detail(env,row['binding_id'])
    assert item['source_key'] == {'id':PARENT}
    assert item['history'][0]['source_values']['area'] == '1.234567890123456789'
    ev = env.query('evidence',TENANT,ACTOR,{'id':row['evidence_id']})
    assert hashlib.sha256(ev['metadata']['canonical_json'].encode()).hexdigest() == ev['content_hash']
    assert ev['metadata']['receipt']['values'] == payload['records'][0]['values']
    assert ev['metadata']['causal_claim'] is False
    entity = env.query('entities',TENANT,ACTOR,{'entity_key':row['entity_key']})['items'][0]
    assert entity['attributes']['place.area'] == {'value':'1.234567890123456789','unit':'ha'}
    changed = deepcopy(payload)
    changed['records'][0]['values']['label'] = '不同内容'
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',changed)
    assert exc.value.code == 'source_batch_conflict'


def test_preview_rolls_back_every_table_and_omits_temporary_ids(env):
    tables = ['entities','evidence','type_assignments','source_bindings','source_binding_revisions',
              'source_batches','relations','source_relation_links','evidence_links','idempotency','outbox','audit_log','outbox_counters']
    before = {t:number(env,t) for t in tables}
    result = env.preview_source_batch(TENANT,ACTOR,batch())
    assert result['read_only'] and result['would_store'] and result['counts']['created'] == 1
    assert not {'binding_id','entity_key','evidence_id'} & set(result['records'][0])
    assert before == {t:number(env,t) for t in tables}


def test_two_stage_import_creates_relations_independent_of_record_order(env):
    payload = batch([
        {'table':'places','values':{'id':CHILD,'label':'合成子场所','parent_id':PARENT}},
        {'table':'places','values':{'id':PARENT,'label':'合成父场所'}},
    ])
    result = write(env,'import_source_batch',payload)
    assert result['counts']['created'] == 2 and result['counts']['relations_created'] == 1
    relations = env.query('relations',TENANT,ACTOR,{'status':'candidate'})['items']
    assert len(relations) == 1 and relations[0]['status'] == 'candidate'
    assert relations[0]['subject_key'] == result['records'][0]['entity_key']
    assert relations[0]['object_key'] == result['records'][1]['entity_key']
    assert relations[0]['qualifiers']['temporal_basis'] == 'source_snapshot_not_business_event'
    assert relations[0]['qualifiers']['source_snapshot_at'].startswith('2025-01-01')


def test_missing_reference_or_invalid_later_row_rolls_back_all(env):
    tables = ['entities','evidence','source_bindings','source_binding_revisions','source_batches','type_assignments','relations','idempotency','outbox']
    before = {t:number(env,t) for t in tables}
    payload = batch([{'table':'places','values':{'id':CHILD,'label':'缺目标','parent_id':PARENT}}])
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',payload)
    assert inner_code(exc) == 'unresolved_source_reference'
    assert before == {t:number(env,t) for t in tables}
    payload['records'][0]['values'].pop('parent_id')
    payload['records'].append({'table':'places','values':{'id':PARENT}})
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',payload)
    assert inner_code(exc) == 'required_attribute'
    assert before == {t:number(env,t) for t in tables}


def test_patch_revision_nullable_fk_close_and_history_preservation(env):
    first = write(env,'import_source_batch',batch([
        {'table':'places','values':{'id':PARENT,'label':'父'}},
        {'table':'places','values':{'id':CHILD,'label':'子','parent_id':PARENT,'area':'2'}}]))
    child = first['records'][1]
    second = write(env,'import_source_batch',batch([
        {'table':'places','values':{'id':CHILD,'label':'子修订','area':None,'parent_id':None},'expected_revision':1}],LATER))
    assert second['counts']['updated'] == 1 and second['counts']['relations_closed'] == 1
    assert second['records'][0]['entity_key'] == child['entity_key']
    item = detail(env,child['binding_id'])
    assert item['revision'] == 2 and len(item['history']) == 2
    assert item['history'][0]['source_values']['area'] == '2'
    assert item['history'][1]['source_values']['area'] is None
    assert 'place.area' not in item['history'][1]['entity_snapshot']['attributes']
    assert item['relationships'][0]['ended_revision'] == 2
    assert number(env,'relations') == 1 and number(env,'evidence') == 3
    oldev = env.query('evidence',TENANT,ACTOR,{'id':child['evidence_id']})
    assert oldev['status'] == 'active'
    third = write(env,'import_source_batch',batch([
        {'table':'places','values':{'id':CHILD,'parent_id':PARENT},'expected_revision':2}],THIRD))
    assert third['counts']['relations_created'] == 1
    assert number(env,'relations') == 2
    assert len(detail(env,child['binding_id'])['relationships']) == 2


def test_unchanged_relation_is_not_duplicated_when_attribute_changes(env):
    result = write(env,'import_source_batch',batch([
        {'table':'places','values':{'id':PARENT,'label':'父'}},
        {'table':'places','values':{'id':CHILD,'label':'子','parent_id':PARENT}}]))
    updated = write(env,'import_source_batch',batch([
        {'table':'places','values':{'id':CHILD,'area':'3'},'expected_revision':1}],LATER))
    assert updated['counts']['relations_created'] == updated['counts']['relations_closed'] == 0
    assert number(env,'relations') == 1
    assert detail(env,result['records'][1]['binding_id'])['source_values']['label'] == '子'


@pytest.mark.parametrize('expected,at,code',[(None,LATER,'source_revision_conflict'),(0,LATER,'source_revision_conflict'),(1,START,'source_time_regression')])
def test_changed_records_require_explicit_revision_and_later_snapshot(env,expected,at,code):
    write(env,'import_source_batch',batch())
    record = {'table':'places','values':{'id':PARENT,'label':'修改'}}
    if expected is not None:
        record['expected_revision'] = expected
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',batch([record],at))
    assert inner_code(exc) == code
    assert number(env,'source_binding_revisions') == 1


@pytest.mark.parametrize('values,code',[
    ({'area':1.2},'source_decimal_precision'),
    ({'area':'NaN'},'source_decimal_precision'),
    ({'area':'-1'},'property_value_range'),
    ({'date':'2025-02-29'},'source_date_type'),
    ({'date':'2024-2-01'},'source_date_type'),
    ({'at':'2025-01-01T00:00:00'},'invalid_time'),
    ({'count':True},'source_integer_type'),
    ({'count':9007199254740993},'source_integer_precision'),
    ({'labels':[1]},'source_array_type'),
    ({'unknown':'not permitted'},'unmapped_source_field'),
    ({'password':'test-not-a-real-password'},'source_field_rejected'),
])
def test_typed_values_and_unmapped_fields_fail_closed(env,values,code):
    p = batch()
    p['records'][0]['values'].update(values)
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == code
    assert number(env,'entities') == 0 and number(env,'evidence') == 0


def test_explicit_deferred_values_and_empty_text_array_preserved(env):
    p = batch()
    p['records'][0]['values'].update({'labels':[],'geometry':{'type':'Point','coordinates':[114,30]},'count':'9007199254740993','at':'2025-01-01T08:00:00+08:00','date':'2024-02-29'})
    row = write(env,'import_source_batch',p)['records'][0]
    item = detail(env,row['binding_id'])
    assert row['deferred_fields'] == profile()['tables'][0]['deferred_fields']
    assert item['source_values']['labels'] == []
    assert item['source_values']['geometry']['coordinates'] == [114,30]
    attrs = item['history'][0]['entity_snapshot']['attributes']
    assert 'place.labels' not in attrs
    assert attrs['place.count']['value'] == 9007199254740993
    assert attrs['place.at']['value'] == '2025-01-01T00:00:00+00:00'


def test_same_name_does_not_merge_source_identities_and_tenants(env):
    p = batch([{'table':'places','values':{'id':PARENT,'label':'同名'}},{'table':'places','values':{'id':CHILD,'label':'同名'}}])
    result = write(env,'import_source_batch',p)
    assert len({r['entity_key'] for r in result['records']}) == 2
    other_tenant = 'source-test-other'
    other_actor = dict(ACTOR,tenant_id=other_tenant)
    write(env,'install_source_bundle',{'packages':[package()],'profile':profile()},tenant=other_tenant,actor=other_actor)
    other = write(env,'import_source_batch',p,tenant=other_tenant,actor=other_actor)
    assert {r['entity_key'] for r in other['records']}.isdisjoint({r['entity_key'] for r in result['records']})
    assert env.query('source_bindings',other_tenant,other_actor,{'binding_id':result['records'][0]['binding_id']})['items'] == []
    with pytest.raises(DomainError) as exc:
        env.query('source_bindings',other_tenant,ACTOR,{})
    assert exc.value.code == 'tenant_mismatch'


def test_cross_tenant_reference_is_unresolved(env):
    write(env,'import_source_batch',batch())
    other_tenant,other_actor = 'tenant-other',dict(ACTOR,tenant_id='tenant-other')
    write(env,'install_source_bundle',{'packages':[package()],'profile':profile()},tenant=other_tenant,actor=other_actor)
    p = batch([{'table':'places','values':{'id':CHILD,'label':'跨租户引用','parent_id':PARENT}}])
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p,tenant=other_tenant,actor=other_actor)
    assert inner_code(exc) == 'unresolved_source_reference'


def test_profile_immutable_and_property_reference_checked(env):
    p = profile()
    assert write(env,'register_source_profile',p)['content_hash']
    p['label'] = 'changed'
    with pytest.raises(DomainError) as exc:
        write(env,'register_source_profile',p)
    assert exc.value.code == 'immutable_source_profile'
    p['version'] = '1.0.1'
    p['tables'][0]['fields'][0]['property_id'] = 'unknown.property'
    with pytest.raises(DomainError) as exc:
        write(env,'register_source_profile',p)
    assert exc.value.code == 'source_property_not_found'


def test_profile_removal_closes_owned_relation_explicitly(env):
    result = write(env,'import_source_batch',batch([
        {'table':'places','values':{'id':PARENT,'label':'父'}},
        {'table':'places','values':{'id':CHILD,'label':'子','parent_id':PARENT}}]))
    new = profile()
    new['version'] = '1.0.1'
    new['tables'][0]['relations'] = []
    new['tables'][0]['deferred_fields'].append({'field':'parent_id','reason':'停止将源父关系投影，原字段保留'})
    write(env,'register_source_profile',new)
    p = batch([{'table':'places','values':{'id':CHILD},'expected_revision':1}],LATER)
    p['version'] = '1.0.1'
    changed = write(env,'import_source_batch',p)
    assert changed['counts']['relations_closed'] == 1
    assert detail(env,result['records'][1]['binding_id'])['revision'] == 2


def test_duplicate_source_key_normalizes_uuid_and_rolls_back(env):
    p = batch([{'table':'places','values':{'id':PARENT,'label':'一'}},{'table':'places','values':{'id':PARENT.upper(),'label':'二'}}])
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'duplicate_source_record'
    assert number(env,'entities') == 0


def test_payload_limits_and_unknown_uuid_input_fields(env):
    p = batch()
    p['records'][0]['entity_key'] = str(uuid4())
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert exc.value.code == 'schema_validation_failed'
    p = batch()
    p['records'] *= 101
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert exc.value.code == 'schema_validation_failed'
    p = batch()
    p['records'][0]['values']['geometry'] = 'x' * (2*1024*1024)
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert exc.value.status == 413


def test_external_entity_change_cannot_be_silently_overwritten(env):
    row = write(env,'import_source_batch',batch())['records'][0]
    with env.db.transaction() as tx:
        tx.execute('UPDATE entities SET revision=revision+1 WHERE tenant_id=%s AND entity_key=%s',(TENANT,row['entity_key']))
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',batch([{'table':'places','values':{'id':PARENT,'label':'来源更新'},'expected_revision':1}],LATER))
    assert inner_code(exc) == 'source_entity_conflict'


def test_install_and_batch_preview_is_atomic_on_fresh_tenant(database):
    service = SourceMappingService(database)
    body = {'packages':[package()],'profile':profile(),'batch':batch()}
    result = service.preview_source_bundle(TENANT,ACTOR,body)
    assert result['batch']['counts']['created'] == 1
    for table in ['ontology_packages','source_profiles','source_bindings','source_batches','outbox_counters','evidence']:
        assert number(service,table) == 0
    failed = deepcopy(body)
    failed['batch']['records'][0]['values']['parent_id'] = CHILD
    with pytest.raises(DomainError):
        write(service,'install_source_bundle',failed)
    for table in ['ontology_packages','source_profiles','source_bindings','source_batches','outbox_counters','evidence','idempotency']:
        assert number(service,table) == 0
    applied = write(service,'install_source_bundle',body)
    assert applied['package_count'] == 1 and applied['batch']['counts']['created'] == 1


def test_roles_are_admin_or_ontology_admin_only(env):
    for role in ['reader','operator','reviewer']:
        actor = dict(ACTOR,roles=[role])
        with pytest.raises(DomainError) as exc:
            write(env,'import_source_batch',batch(),actor=actor)
        assert exc.value.status == 403
        with pytest.raises(DomainError) as exc:
            env.preview_source_batch(TENANT,actor,batch())
        assert exc.value.status == 403


def test_parallel_identical_source_record_has_one_identity(env):
    p = batch()
    def run(i):
        return write(env,'import_source_batch',dict(p,batch_id='parallel-'+str(i)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,range(2)))
    assert sum(r['counts']['created'] for r in results) == 1
    assert sum(r['counts']['unchanged'] for r in results) == 1
    assert number(env,'entities') == 1 and number(env,'source_binding_revisions') == 1
    assert results[0]['records'][0]['entity_key'] == results[1]['records'][0]['entity_key']


def test_parallel_updates_one_optimistic_revision_wins(env):
    write(env,'import_source_batch',batch())
    def run(i):
        try:
            return write(env,'import_source_batch',batch([{'table':'places','values':{'id':PARENT,'label':'并发'+str(i)},'expected_revision':1}],LATER))
        except DomainError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,range(2)))
    assert sum(isinstance(x,dict) for x in results) == 1
    error = next(x for x in results if isinstance(x,DomainError))
    assert error.details[0]['code'] == 'source_revision_conflict'
    assert number(env,'source_binding_revisions') == 2


def test_large_integer_strings_fail_with_domain_errors_and_int64_minimum_is_valid(env):
    p = batch()
    p['records'][0]['values']['count'] = '9' * 5000
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'source_integer_precision'
    p['records'][0]['values']['count'] = '-9223372036854775808'
    result = write(env,'import_source_batch',p)
    snapshot = detail(env,result['records'][0]['binding_id'])['history'][0]['entity_snapshot']
    assert snapshot['attributes']['place.count']['value'] == -9223372036854775808
    integer_profile = profile()
    integer_profile['source_id'] = 'integer-source'
    integer_profile['tables'][0]['key_types']['id'] = 'integer'
    write(env,'register_source_profile',integer_profile)
    p = batch([{'table':'places','values':{'id':'9'*5000,'label':'invalid huge key'}}])
    p['source_id'] = 'integer-source'
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'invalid_source_key'


def test_primary_key_contract_cannot_change_via_another_profile(env):
    write(env,'import_source_batch',batch())
    changed = profile()
    changed['version'] = '2.0.0'
    changed['tables'][0]['primary_key'] = ['code']
    changed['tables'][0]['key_types'] = {'code':'string'}
    changed['tables'][0]['relations'][0]['target_fields'] = ['code']
    with pytest.raises(DomainError) as exc:
        write(env,'register_source_profile',changed)
    assert exc.value.code == 'source_type_migration_required'
    assert number(env,'entities') == 1


def test_preinstalled_incompatible_profile_cannot_duplicate_identity(env):
    alternate = profile()
    alternate['version'] = '2.0.0'
    alternate['tables'][0]['key_types'] = {'id':'string'}
    write(env,'register_source_profile',alternate)
    write(env,'import_source_batch',batch())
    p = batch([{'table':'places','values':{'id':PARENT.upper(),'label':'try alternate key normalization'}}])
    p['version'] = '2.0.0'
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'source_type_migration_required'
    assert number(env,'entities') == 1


def test_uuid_primary_keys_reject_json_numbers(env):
    p = batch()
    p['records'][0]['values']['id'] = 12345678901234567890123456789012
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'invalid_source_key'


def test_source_snapshot_evidence_is_separate_and_withdrawal_disables_reference(env):
    row = write(env,'import_source_batch',batch())['records'][0]
    bundle = env.query('evidence_bundle',TENANT,ACTOR,{'entity_key':row['entity_key']})
    assert bundle['observations'] == bundle['candidate_assertions'] == bundle['adopted_assertions'] == []
    assert bundle['source_snapshots'][0]['information_nature'] == 'source_snapshot'
    assert bundle['source_snapshots'][0]['eligible_for_reference'] is True
    assert bundle['source_snapshots'][0]['usable_for_inference'] is False
    assert bundle['source_snapshots'][0]['data_nature'] == 'synthetic'
    assert row['evidence_id'] in {x['id'] for x in bundle['evidence']}
    assert not any(x['code'] == 'no_records' for x in bundle['gaps'])
    body = dict(bundle)
    digest = body.pop('content_hash')
    assert hashlib.sha256(_json(body).encode()).hexdigest() == digest
    write(env,'withdraw_evidence',{'evidence_id':row['evidence_id'],'reason':'synthetic withdrawal'},actor=dict(ACTOR,roles=['admin']))
    withdrawn = env.query('evidence_bundle',TENANT,ACTOR,{'entity_key':row['entity_key']})
    assert withdrawn['source_snapshots'][0]['eligible_for_reference'] is False
    assert any(x['code'] == 'source_evidence_withdrawn' for x in withdrawn['gaps'])


def test_history_pagination_returns_continuation_and_rejects_huge_offset(env):
    row = write(env,'import_source_batch',batch())['records'][0]
    for revision,at in [(1,LATER),(2,THIRD)]:
        write(env,'import_source_batch',batch([{'table':'places','values':{'id':PARENT,'label':'revision '+str(revision)},'expected_revision':revision}],at))
    first = env.query('source_bindings',TENANT,ACTOR,{'binding_id':row['binding_id'],'history_limit':2})['items'][0]
    assert [x['revision'] for x in first['history']] == [1,2]
    assert first['history_page']['has_more'] and first['history_page']['next_offset'] == 2
    second = env.query('source_bindings',TENANT,ACTOR,{'binding_id':row['binding_id'],'history_limit':2,'history_offset':2})['items'][0]
    assert [x['revision'] for x in second['history']] == [3]
    assert second['history_page']['has_more'] is False
    with pytest.raises(DomainError) as exc:
        env.query('source_bindings',TENANT,ACTOR,{'binding_id':row['binding_id'],'history_offset':'9'*5000})
    assert exc.value.code == 'invalid_pagination'


def test_synthetic_record_cannot_be_relabelled_as_production(env):
    write(env,'import_source_batch',batch())
    p = batch([{'table':'places','values':{'id':PARENT},'expected_revision':1}],LATER)
    p['data_nature'] = 'production'
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'source_data_nature_conflict'


def test_bundle_reinstallation_preserves_display_labels_and_existing_entities(env):
    row = write(env,'import_source_batch',batch())['records'][0]
    current = env.query('packages',TENANT,ACTOR,{'package_id':'test.source','version':'1.0.0'})['items'][0]
    write(env,'update_package_labels',{'package_id':'test.source','version':'1.0.0',
                                      'expected_revision':current['display_revision'],'label':'管理员正式名称'})
    before = detail(env,row['binding_id'])
    result = write(env,'install_source_bundle',{'packages':[package()],'profile':profile()})
    assert result['package_count'] == 1 and 'batch' not in result
    assert number(env,'entities') == 1 and detail(env,row['binding_id']) == before
    assert env.query('packages',TENANT,ACTOR,{'package_id':'test.source','version':'1.0.0'})['items'][0]['label'] == '管理员正式名称'


def test_two_stage_cycle_and_composite_fk_mapping(env):
    p = batch([
        {'table':'places','values':{'id':PARENT,'label':'环一','parent_id':CHILD}},
        {'table':'places','values':{'id':CHILD,'label':'环二','parent_id':PARENT}},
    ])
    result = write(env,'import_source_batch',p)
    assert result['counts']['created'] == 2 and result['counts']['relations_created'] == 2
    composite = profile()
    composite['source_id'] = 'composite-source'
    table = composite['tables'][0]
    table['primary_key'] = ['zone','code']
    table['key_types'] = {'zone':'string','code':'integer'}
    table['relations'][0]['fields'] = ['parent_zone','parent_code']
    table['relations'][0]['target_fields'] = ['zone','code']
    write(env,'register_source_profile',composite)
    p = batch([
        {'table':'places','values':{'zone':'A','code':'9007199254740993','label':'大编号父'}},
        {'table':'places','values':{'zone':'B','code':1,'label':'复合子','parent_zone':'A','parent_code':'9007199254740993'}},
    ])
    p['source_id'] = 'composite-source'
    result = write(env,'import_source_batch',p)
    assert result['counts']['relations_created'] == 1
    assert result['records'][0]['source_key'] == {'zone':'A','code':'9007199254740993'}
    changed = batch([{'table':'places','values':{'zone':'B','code':1,'parent_zone':None},'expected_revision':1}],LATER)
    changed['source_id'] = 'composite-source'
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',changed)
    assert inner_code(exc) == 'partial_source_reference'
    changed['records'][0]['values']['parent_code'] = None
    result = write(env,'import_source_batch',changed)
    assert result['counts']['relations_closed'] == 1


def test_required_reference_and_irreflexive_relation_fail_atomically(env):
    required = profile()
    required['source_id'] = 'required-ref-source'
    required['tables'][0]['relations'][0]['nullable'] = False
    write(env,'register_source_profile',required)
    p = batch()
    p['source_id'] = 'required-ref-source'
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'source_reference_required'
    assert number(env,'source_bindings') == 0
    p['records'][0]['values']['parent_id'] = PARENT
    with pytest.raises(DomainError) as exc:
        write(env,'import_source_batch',p)
    assert inner_code(exc) == 'relation_self_loop'
    assert number(env,'source_bindings') == 0 and number(env,'relations') == 0


@pytest.mark.parametrize('unit',[None,'mu'])
def test_unit_bearing_mapping_requires_explicit_equal_source_unit(env,unit):
    p = profile()
    p['version'] = '1.0.1'
    field = p['tables'][0]['fields'][1]
    if unit is None:
        field.pop('source_unit')
    else:
        field['source_unit'] = unit
    with pytest.raises(DomainError) as exc:
        write(env,'register_source_profile',p)
    assert exc.value.code == 'source_unit_declaration'


def test_row_units_are_validated_preserved_and_not_implicitly_converted(env):
    p = profile()
    p['version'] = '1.0.1'
    p['tables'][0]['fields'][1]['source_unit_field'] = 'area_unit'
    write(env,'register_source_profile',p)
    request = batch()
    request['version'] = '1.0.1'
    for unit in [None,'mu','m2']:
        if unit is not None:
            request['records'][0]['values']['area_unit'] = unit
        with pytest.raises(DomainError) as exc:
            write(env,'import_source_batch',request)
        assert inner_code(exc) == 'source_unit_mismatch'
        assert number(env,'source_bindings') == 0
    request['records'][0]['values']['area_unit'] = 'ha'
    result = write(env,'import_source_batch',request)
    binding = detail(env,result['records'][0]['binding_id'])
    assert binding['source_values']['area_unit'] == 'ha'
    assert binding['history'][0]['entity_snapshot']['attributes']['place.area']['unit'] == 'ha'
    no_units = profile()
    no_units['version'] = '1.0.2'
    no_units['tables'][0]['fields'][0]['source_unit'] = 'ha'
    with pytest.raises(DomainError) as exc:
        write(env,'register_source_profile',no_units)
    assert exc.value.code == 'unexpected_source_unit'


def test_binding_identity_projection_omits_source_payloads_and_history(env):
    row = write(env,'import_source_batch',batch())['records'][0]
    result = env.query('source_bindings',TENANT,ACTOR,{'binding_id':row['binding_id'],'projection':'identity'})['items'][0]
    assert result['source_key'] == {'id':PARENT} and result['table'] == 'places'
    assert result['revision'] == 1 and result['data_nature'] == 'synthetic'
    assert not {'source_values','history','relationships','evidence_id','payload_hash'} & set(result)
    with pytest.raises(DomainError) as exc:
        env.query('source_bindings',TENANT,ACTOR,{'binding_id':row['binding_id'],'projection':'identity','history_limit':1})
    assert exc.value.code == 'projection_history_conflict'
