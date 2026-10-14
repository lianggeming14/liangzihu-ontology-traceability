"""Ontology v0.3: exact mapping, immutable releases and display-only edits."""
from copy import deepcopy
from uuid import uuid4
import pytest
from agri.ontology_core import OntologyService, validate_property_value
from agri.service import Service, DomainError

ACTOR={'id':'ontology-test','roles':['admin']}
TENANT='core-test'
AT='2026-10-01T00:00:00+00:00'

def package(version='1.0.0'):
    return {'package_id':'farm.water','version':version,'namespace':'https://example.test/water/','label':'水环境本体','description':'测试定义',
      'types':[{'type_id':'water:Field','identity_type':'field','label':'水田'},{'type_id':'water:Sensor','identity_type':'device','label':'传感器'}],
      'properties':[
        {'property_id':'area','label':'面积','applies_to':['water:Field'],'usage':'attribute','value_type':'decimal','unit':'ha','required':True},
        {'property_id':'water.temp','label':'水温','applies_to':['water:Field'],'usage':'observation','value_type':'decimal','unit':'Cel','minimum':-5,'maximum':80},
        {'property_id':'water.grade','label':'等级','applies_to':['water:Field'],'usage':'assertion','value_type':'enum','enum_values':['A','B']},
        {'property_id':'enabled','label':'启用','applies_to':['water:Sensor'],'usage':'attribute','value_type':'boolean'},
      ],
      'predicates':[{'predicate_id':'monitors','label':'监测','subject_types':['device'],'object_types':['field'],'subject_semantic_types':['water:Sensor'],'object_semantic_types':['water:Field'],'dimension':'observation'}]}

@pytest.fixture
def core(database): return OntologyService(database)

def write(core,action,payload,tenant=TENANT,key=None,actor=None):
    return core.mutate(action,tenant,actor or ACTOR,payload,key or str(uuid4()))

def populated(core):
    pkg=write(core,'register_package',package())
    field=write(core,'create_entity',{'entity_type':'field','name':'测试田','attrs':{'area':{'value':'2.5','unit':'ha'}},'semantic_types':[{'package_id':'farm.water','version':'1.0.0','type_id':'water:Field','valid_from':'2020-01-01T00:00:00Z'}]})
    ev=write(core,'create_evidence',{'kind':'manual','uri':'urn:test:receipt','content_hash':'a'*64})
    return pkg,field,ev

def observation(field,ev,**updates):
    return {'subject_key':field['entity_key'],'property_id':'water.temp','value':{'value':'22.4','unit':'Cel'},'observed_at':AT,'method':'sensor-api','evidence_ids':[ev['id']],**updates}

def error(code,fn):
    with pytest.raises(DomainError) as e: fn()
    assert e.value.code==code


def test_registered_observation_pins_exact_reference_and_retains_typed_value(core):
    pkg,field,ev=populated(core)
    body=observation(field,ev);result=write(core,'create_observation',body,key='stable')
    assert result['validation_status']=='validated'
    assert result['property_ref']=={'package_id':'farm.water','version':'1.0.0','property_id':'water.temp'}
    assert result['value_json']==body['value']
    assert write(core,'create_observation',body,key='stable')==result
    rows=core.query('observations',TENANT,ACTOR,{'entity_key':field['entity_key']})['items']
    assert len(rows)==1 and rows[0]['property_ref']==result['property_ref']
    error('idempotency_conflict',lambda:write(core,'create_observation',dict(body,method='other'),key='stable'))

@pytest.mark.parametrize('change,code',[
 ({'property_id':'temperature'},'needs_mapping'),
 ({'value':{'value':'22','unit':'F'}},'property_unit_mismatch'),
 ({'value':{'value':True,'unit':'Cel'}},'property_value_type'),
 ({'value':{'value':'NaN','unit':'Cel'}},'property_value_type'),
 ({'value':{'value':'90','unit':'Cel'}},'property_value_range'),
 ({'property_ref':{'package_id':'farm.water','version':'2.0.0','property_id':'water.temp'}},'needs_mapping'),
 ({'property_ref':{'package_id':'farm.water','version':'1.0.0','property_id':'different'}},'property_reference_mismatch'),
 ({'observed_at':'2019-01-01T00:00:00Z'},'needs_mapping'),
])
def test_invalid_observation_is_atomic(core,change,code):
    pkg,field,ev=populated(core)
    before=core.query('changes',TENANT,ACTOR)['items']
    error(code,lambda:write(core,'create_observation',observation(field,ev,**change),key='retryable'))
    assert not core.query('observations',TENANT,ACTOR)['items']
    assert len(core.query('changes',TENANT,ACTOR)['items'])==len(before)
    assert write(core,'create_observation',observation(field,ev),key='retryable')['validation_status']=='validated'


def test_label_change_is_revisioned_and_does_not_change_release_or_mapping(core):
    pkg,field,ev=populated(core)
    update={'package_id':'farm.water','version':'1.0.0','expected_revision':1,'label':'梁子湖水环境','type_labels':{'water:Field':'稻田'},'property_labels':{'water.temp':'田间水温'},'predicate_labels':{'monitors':'监测田块'}}
    result=write(core,'update_package_labels',update,key='labels')
    assert result['label']=='梁子湖水环境' and result['display_revision']==2
    assert result['content_hash']==pkg['content_hash'] and result['definition']==pkg['definition']
    assert result['types'][0]['label']=='稻田'
    assert write(core,'update_package_labels',update,key='labels')==result
    error('display_revision_conflict',lambda:write(core,'update_package_labels',update))
    error('unknown_label_target',lambda:write(core,'update_package_labels',dict(update,expected_revision=2,property_labels={'bogus':'x'})))
    prop=core.query('properties',TENANT,ACTOR,{'entity_key':field['entity_key'],'usage':'observation'})['items'][0]
    assert prop['label']=='田间水温' and prop['property_id']=='water.temp'
    assert write(core,'create_observation',observation(field,ev))['validation_status']=='validated'
    error('immutable_release',lambda:write(core,'register_package',dict(package(),label='另一名字')))


def test_tenant_and_role_isolation(core):
    pkg,field,ev=populated(core)
    assert core.query('packages','other',ACTOR)['items']==[]
    assert core.query('properties','other',ACTOR)['items']==[]
    error('package_not_found',lambda:write(core,'update_package_labels',{'package_id':'farm.water','version':'1.0.0','expected_revision':1,'label':'x'},tenant='other'))
    error('forbidden',lambda:write(core,'update_package_labels',{'package_id':'farm.water','version':'1.0.0','expected_revision':1,'label':'x'},actor={'id':'reader','roles':['reader']}))
    error('entity_not_found',lambda:write(core,'create_observation',observation(field,ev),tenant='other'))


def test_class_property_attributes_and_required_rules(core):
    write(core,'register_package',package())
    common={'entity_type':'field','name':'田','semantic_types':[{'package_id':'farm.water','version':'1.0.0','type_id':'water:Field'}]}
    error('required_attribute',lambda:write(core,'create_entity',common))
    error('unknown_attribute',lambda:write(core,'create_entity',dict(common,attrs={'foo':1})))
    error('property_unit_mismatch',lambda:write(core,'create_entity',dict(common,attrs={'area':'1'})))
    good=write(core,'create_entity',dict(common,attrs={'area':{'value':'1','unit':'ha'},'synthetic':True}))
    assert good['validation_status']=='validated'
    assert len(core.query('entities',TENANT,ACTOR)['items'])==1


def test_definition_cannot_reference_missing_class_or_invalid_enum(core):
    bad=package();bad['properties'][0]['applies_to']=['missing']
    error('unknown_property_class',lambda:write(core,'register_package',bad))
    bad=package();bad['properties'][2].pop('enum_values')
    error('enum_values_required',lambda:write(core,'register_package',bad))
    bad=package();bad['predicates'][0]['subject_semantic_types']=['water:Field']
    error('relation_class_identity',lambda:write(core,'register_package',bad))
    assert core.query('packages',TENANT,ACTOR)['items']==[]


def test_ambiguous_versions_require_explicit_property_reference(core):
    first=package(); first['properties']=[x for x in first['properties'] if x['usage']=='observation']
    second=deepcopy(first);second['version']='2.0.0'
    write(core,'register_package',first);write(core,'register_package',second)
    field=write(core,'create_entity',{'entity_type':'field','name':'田','semantic_types':[{'package_id':'farm.water','version':version,'type_id':'water:Field','valid_from':'2020-01-01T00:00:00Z'} for version in ['1.0.0','2.0.0']]})
    ev=write(core,'create_evidence',{'kind':'manual','uri':'urn:test','content_hash':'a'*64})
    error('needs_mapping',lambda:write(core,'create_observation',observation(field,ev)))
    ref={'package_id':'farm.water','version':'2.0.0','property_id':'water.temp'}
    assert write(core,'create_observation',observation(field,ev,property_ref=ref))['property_ref']==ref


def test_assertions_require_mapping_before_acceptance_and_keep_candidates(core):
    pkg,field,ev=populated(core)
    body={'subject_key':field['entity_key'],'predicate_id':'water.grade','value':{'value':'A'},'origin':'model','evidence_ids':[ev['id']]}
    result=write(core,'create_assertion',body)
    assert result['status']=='candidate' and result['validation_status']=='unvalidated'
    error('assertion_mapping_required',lambda:write(core,'review_assertion',{'assertion_id':result['id'],'status':'accepted','rationale':'不能代替映射'}))
    ref={'package_id':'farm.water','version':'1.0.0','property_id':'water.grade'}
    good=write(core,'create_assertion',dict(body,property_ref=ref))
    assert good['validation_status']=='validated'
    accepted=write(core,'review_assertion',{'assertion_id':good['id'],'status':'accepted','rationale':'人工审核'})
    assert accepted['status']=='accepted' and accepted['property_ref']==ref
    error('property_value_type',lambda:write(core,'create_assertion',dict(body,property_ref=ref,value={'value':'C'})))


def test_relation_semantic_endpoints_use_exact_version_and_valid_interval(core):
    pkg,field,ev=populated(core)
    device=write(core,'create_entity',{'entity_type':'device','name':'未分类传感器'})
    body={'subject_key':device['entity_key'],'object_key':field['entity_key'],'package_id':'farm.water','package_version':'1.0.0','predicate_id':'monitors','valid_from':AT,'evidence_ids':[ev['id']]}
    error('relation_semantic_type',lambda:write(core,'create_relation',body))
    write(core,'assign_type',{'entity_key':device['entity_key'],'package_id':'farm.water','version':'1.0.0','type_id':'water:Sensor','valid_from':'2020-01-01T00:00:00Z','valid_to':'2027-01-01T00:00:00Z'})
    error('relation_semantic_type',lambda:write(core,'create_relation',body))
    result=write(core,'create_relation',dict(body,valid_to='2026-12-31T00:00:00Z'))
    assert result['predicate_id']=='monitors'


def test_legacy_data_readable_without_false_validation(core):
    old=Service(core.db)
    entity=write(old,'create_entity',{'entity_type':'field','name':'旧对象','attrs':{'free':'retained'}})
    ev=write(old,'create_evidence',{'kind':'document','uri':'urn:legacy','content_hash':'b'*64})
    obs=write(old,'create_observation',{'subject_key':entity['entity_key'],'property_id':'old.free','value':{'value':'x'},'observed_at':AT,'method':'legacy','evidence_ids':[ev['id']]})
    rows=core.query('observations',TENANT,ACTOR)['items']
    assert rows[0]['id']==obs['id'] and rows[0]['validation_status']=='legacy_unvalidated'
    assert core.query('entity',TENANT,ACTOR,{'id':entity['entity_key']})['attributes']=={'free':'retained'}
    error('needs_mapping',lambda:write(core,'create_observation',{'subject_key':entity['entity_key'],'property_id':'old.free','value':{'value':'x'},'observed_at':AT,'method':'new','evidence_ids':[ev['id']]}))


def test_builtin_gate_properties_cannot_be_used_on_arbitrary_entities(core):
    pkg,field,ev=populated(core)
    error('builtin_device_required',lambda:write(core,'create_observation',observation(field,ev,property_id='gate.state',value={'value':'open','unit':'1'})))
    device=write(core,'register_device',{'name':'闸门','device_kind':'gate','source_id':'gate-api','external_device_id':'G1','bound_entity_key':field['entity_key']})
    receipt=write(core,'ingest_device_record',{'device_id':device['id'],'source_record_id':'g1','record_type':'gate_status','captured_at':AT,'data':{'state':'partial','position_pct':'40'},'evidence_ids':[ev['id']]})
    assert len(receipt['observation_ids'])==2
    assert all(r['validation_status']=='builtin_validated' for r in core.query('observations',TENANT,ACTOR)['items'])

@pytest.mark.parametrize('definition,value,code',[
 ({'value_type':'integer'},True,'property_value_type'),
 ({'value_type':'boolean'},'true','property_value_type'),
 ({'value_type':'string','cardinality':'single'},['x'],'property_cardinality'),
 ({'value_type':'string','cardinality':'many'},'x','property_cardinality'),
 ({'value_type':'datetime'},'2026-10-01','property_value_type'),
])
def test_value_type_contracts(definition,value,code):
    error(code,lambda:validate_property_value({'property_id':'x','usage':'attribute',**definition},{'value':value}))


def test_legacy_observation_and_assertion_are_not_validated_in_bundle(core):
    old=Service(core.db)
    entity=write(old,'create_entity',{'entity_type':'field','name':'旧田'})
    receipt={'record':'synthetic'}
    from agri.service import _json
    import hashlib
    canonical=_json(receipt)
    ev=write(old,'create_evidence',{'kind':'manual','uri':'urn:test','content_hash':hashlib.sha256(canonical.encode()).hexdigest(),'metadata':{'receipt_format':'manual-receipt/1','canonical_json':canonical,'receipt':receipt}})
    obs=write(old,'create_observation',{'subject_key':entity['entity_key'],'property_id':'free','value':{'value':'2'},'observed_at':AT,'method':'legacy','evidence_ids':[ev['id']]})
    assertion=write(old,'create_assertion',{'subject_key':entity['entity_key'],'predicate_id':'free','value':{'value':'ok'},'evidence_ids':[ev['id']]})
    write(old,'review_assertion',{'assertion_id':assertion['id'],'status':'accepted','rationale':'旧审核'})
    bundle=core.query('evidence_bundle',TENANT,ACTOR,{'entity_key':entity['entity_key']})
    assert bundle['observations'][0]['validation_status']=='legacy_unvalidated'
    assert bundle['observations'][0]['usable_for_inference'] is False
    assert not bundle['adopted_assertions']
    assert bundle['candidate_assertions'][0]['status']=='accepted'
    assert any(g['code']=='observation_mapping_required' for g in bundle['gaps'])


def test_demo_is_strict_validated_and_idempotent(core):
    from agri.ontology_core import seed_core_demo
    first=seed_core_demo(core);second=seed_core_demo(core)
    assert first==second and first['synthetic']
    entity=core.query('entity','demo-farm',ACTOR,{'id':first['field_key']})
    assert entity['validation_status']=='validated'
    properties=core.query('properties','demo-farm',ACTOR,{'entity_key':first['field_key'],'usage':'observation'})['items']
    assert len(properties)==3


def test_attribute_collision_in_new_class_assignment_rolls_back(core):
    pkg,field,ev=populated(core)
    write(core,'register_package',package('2.0.0'))
    before=core.query('entity',TENANT,ACTOR,{'id':field['entity_key']})
    error('ambiguous_attribute',lambda:write(core,'assign_type',{'entity_key':field['entity_key'],'package_id':'farm.water','version':'2.0.0','type_id':'water:Field','valid_from':'2020-01-01T00:00:00Z'}))
    after=core.query('entity',TENANT,ACTOR,{'id':field['entity_key']})
    assert after['semantic_types']==before['semantic_types'] and after['revision']==before['revision']


def test_multiple_classes_validate_complete_attribute_set(core):
    pkg=package();pkg['types'].append({'type_id':'water:Licensed','identity_type':'field','label':'登记田块'})
    pkg['properties'].append({'property_id':'permit','label':'登记号','applies_to':['water:Licensed'],'usage':'attribute','value_type':'string','required':True})
    write(core,'register_package',pkg)
    entity=write(core,'create_entity',{'entity_type':'field','name':'多类田块','attrs':{'area':{'value':'2','unit':'ha'},'permit':'REG1'},'semantic_types':[{'package_id':'farm.water','version':'1.0.0','type_id':kind} for kind in ['water:Field','water:Licensed']]})
    assert len(entity['semantic_types'])==2 and entity['validation_status']=='validated'


def test_manual_intake_uses_same_property_validation_and_keeps_receipt_atomic(core):
    pkg,field,ev=populated(core)
    body={'record_kind':'observation','payload':observation(field,ev,property_ref={'package_id':'farm.water','version':'1.0.0','property_id':'water.temp'}),'note':'现场读数'}
    result=write(core,'ingest_manual',body)
    assert result['record']['validation_status']=='validated'
    assert result['evidence']['id'] in result['record']['evidence_ids']
    before=len(core.query('evidence',TENANT,ACTOR)['items'])
    broken=deepcopy(body);broken['payload']['value']['unit']='F'
    error('property_unit_mismatch',lambda:write(core,'ingest_manual',broken))
    assert len(core.query('evidence',TENANT,ACTOR)['items'])==before
    event=write(core,'ingest_manual',{'record_kind':'event','payload':{'event_type':'inspection','occurred_at':AT,'participants':[{'entity_key':field['entity_key'],'role':'inspected'}],'evidence_ids':[]},'note':'现场巡查记录'})
    assert event['record']['event_type']=='inspection'


def test_relation_acceptance_rechecks_legacy_semantic_endpoints(core):
    pkg,field,ev=populated(core)
    device=write(core,'create_entity',{'entity_type':'device','name':'未分类设备'})
    old=Service(core.db)
    relation=write(old,'create_relation',{'subject_key':device['entity_key'],'object_key':field['entity_key'],'package_id':'farm.water','package_version':'1.0.0','predicate_id':'monitors','valid_from':AT,'evidence_ids':[ev['id']]})
    error('relation_semantic_type',lambda:write(core,'review_relation',{'relation_id':relation['id'],'status':'accepted','rationale':'必须先分类'}))


def test_rename_audit_records_previous_and_current_names(core):
    pkg,field,ev=populated(core)
    write(core,'update_package_labels',{'package_id':'farm.water','version':'1.0.0','expected_revision':1,'label':'正式水环境'})
    import json
    with core.db.transaction() as tx:
        row=tx.execute('SELECT details FROM audit_log WHERE tenant_id=%s AND action=%s',(TENANT,'ontology.display.changed')).fetchone()
        details=json.loads(row['details']) if isinstance(row['details'],str) else row['details']
        assert details['before']['label']=='水环境本体' and details['after']['label']=='正式水环境'
        assert details['previous_revision']==1 and details['revision']==2


def test_future_observation_rejected_consistently_for_direct_and_manual(core):
    from datetime import datetime, timedelta, timezone
    pkg,field,ev=populated(core)
    future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    body=observation(field,ev,observed_at=future)
    before=len(core.query('evidence',TENANT,ACTOR)['items'])
    error('future_observation',lambda:write(core,'create_observation',body))
    error('future_observation',lambda:write(core,'ingest_manual',{'record_kind':'observation','payload':body,'note':'未来不能作实测'}))
    assert core.query('observations',TENANT,ACTOR)['items']==[]
    assert len(core.query('evidence',TENANT,ACTOR)['items'])==before
    forecast=write(core,'create_assertion',{'subject_key':field['entity_key'],'predicate_id':'water.grade','property_ref':{'package_id':'farm.water','version':'1.0.0','property_id':'water.grade'},'value':{'value':'A','context':{'valid_at':future}},'origin':'forecast','evidence_ids':[ev['id']]})
    assert forecast['origin']=='forecast' and forecast['status']=='candidate'


def test_legacy_demo_labels_preserve_release_and_admin_changes(core,tmp_path):
    from agri.seed import seed_demo
    from agri.ontology_core import seed_core_demo
    seed_demo(Service(core.db),tmp_path,persist_manifest=False)
    actor={'id':'demo-label-admin','roles':['admin']};tenant='demo-farm'
    before={x['package_id']:x for x in core.query('packages',tenant,actor)['items']}
    seed_core_demo(core)
    renamed={x['package_id']:x for x in core.query('packages',tenant,actor)['items']}
    for package_id,label in {'agri.core':'农业通用本体（合成示例）','agri.rice-crayfish':'虾稻共作本体（合成示例）','agri.vegetable':'蔬菜生产本体（合成示例）','agri.poultry':'禽蛋生产本体（合成示例）'}.items():
        assert renamed[package_id]['label']==label and renamed[package_id]['display_revision']==1
        assert renamed[package_id]['definition']==before[package_id]['definition']
        assert renamed[package_id]['content_hash']==before[package_id]['content_hash']
    write(core,'update_package_labels',{'package_id':'agri.core','version':'1.0.0','expected_revision':1,'label':'管理员自定义名称'},tenant=tenant,actor=actor)
    seed_core_demo(core)
    after=core.query('packages',tenant,actor,{'package_id':'agri.core'})['items'][0]
    assert after['label']=='管理员自定义名称' and after['display_revision']==2


def test_demo_labels_do_not_rename_non_seed_packages(core):
    from agri.ontology_core import seed_core_demo
    old=Service(core.db)
    write(old,'register_package',{'package_id':'agri.core','version':'1.0.0','namespace':'https://example.org/agri/core/','types':[{'type_id':'custom:Field','identity_type':'field','label':'田块'}],'predicates':[]},tenant='demo-farm')
    seed_core_demo(core)
    row=core.query('packages','demo-farm',ACTOR,{'package_id':'agri.core'})['items'][0]
    assert row['label']=='agri.core' and row['display_revision']==0
