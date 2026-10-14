"""Source mapping and append-only receipt behavior on isolated database backends."""
from copy import deepcopy
import hashlib
from uuid import uuid4
import pytest
from agri.core_intake import IntakeService
from agri.service import DomainError, _now

TENANT='intake-a'
ACTOR={'id':'operator','roles':['admin'],'tenant_id':TENANT}

@pytest.fixture()
def env(database):
    service=IntakeService(database)
    package={'package_id':'water','version':'1.0.0','namespace':'urn:test:water:','label':'水质本体',
        'types':[{'type_id':'pond.water','identity_type':'pond','label':'池塘水体'}], 'predicates':[],
        'properties':[{'property_id':'water.temperature','label':'水温','value_type':'decimal','unit':'Cel','usage':'observation','applies_to':['pond.water'],'minimum':-10,'maximum':80},
          {'property_id':'water.condition','label':'水体情况','value_type':'enum','enum_values':['normal','attention'],'usage':'assertion','applies_to':['pond.water']} ]}
    service.mutate('register_package',TENANT,ACTOR,package,'package')
    entity=service.mutate('create_entity',TENANT,ACTOR,{'name':'测试池塘','entity_type':'pond','semantic_types':[{'package_id':'water','version':'1.0.0','type_id':'pond.water'}]},'entity')
    return service,entity

def mutate(service,action,p,key=None,actor=ACTOR,tenant=TENANT):
    return service.mutate(action,tenant,actor,p,key or str(uuid4()))

def mapping(entity,version='1'):
    return {'mapping_id':'temperature-import','version':version,'source_id':'sensor-platform','schema_version':'v1','record_kind':'observation','target_action':'create_observation','mode':'fields','source_category':'device','content_type':'application/json','subject_key':entity['entity_key'],
      'defaults':{'property_id':'water.temperature','property_ref':{'package_id':'water','version':'1.0.0','property_id':'water.temperature'},'method':'registered source import'},
      'field_rules':[{'source_path':'/readings/temperature','target_path':'/value/value','value_type':'decimal','scale':'0.1','offset':'-10','source_unit_path':'/unit','source_unit':'deci-Cel-offset','unit':'Cel'},
                     {'source_path':'/at','target_path':'/observed_at','value_type':'datetime'}]}

def envelope():
    return {'source_id':'sensor-platform','source_record_id':'r-1','schema_version':'v1','source_category':'device','content_type':'application/json','record_kind':'observation','mapping_id':'temperature-import','mapping_version':'1','payload':{'readings':{'temperature':325},'unit':'deci-Cel-offset','at':_now()}}

def count(service,table):
    with service.db.transaction() as tx:return tx.execute('SELECT COUNT(*) AS n FROM '+table).fetchone()['n']

def test_mapping_conversion_raw_provenance_and_duplicate(env):
    service,entity=env;mutate(service,'register_mapping',mapping(entity));body=envelope()
    result=mutate(service,'receive_intake',body,'first')
    assert result['status']=='stored',result['issues']
    assert result['record']['value_json']=={'value':'22.5','unit':'Cel'}
    assert result['record']['validation_status']=='validated'
    assert result['raw_envelope']==body and result['latest_attempt']==1
    ev=service.query('evidence',TENANT,ACTOR,{'id':result['raw_evidence_id']})
    assert ev['metadata']['receipt']['envelope']==body
    assert hashlib.sha256(ev['metadata']['canonical_json'].encode()).hexdigest()==ev['content_hash']
    assert result['raw_evidence_id'] in result['record']['evidence_ids']
    assert mutate(service,'receive_intake',body,'first')==result
    assert mutate(service,'receive_intake',body,'duplicate-source')['id']==result['id']
    assert count(service,'observations')==1 and count(service,'intake_attempts')==1
    body['payload']['readings']['temperature']=330
    with pytest.raises(DomainError) as error:mutate(service,'receive_intake',body)
    assert error.value.code=='source_record_conflict'

def test_preview_no_persistent_mutation_or_generated_evidence_ids(env):
    service,entity=env;mutate(service,'register_mapping',mapping(entity))
    tables=['evidence','observations','intake_receipts','intake_attempts','audit_log','outbox','idempotency']
    before={table:count(service,table) for table in tables}
    preview=service.preview_intake(TENANT,ACTOR,envelope())
    assert preview['status']=='stored' and preview['would_store'] and preview['read_only']
    assert preview['result'] is None and preview['target_id'] is None
    assert preview['normalized_payload']['evidence_ids']==[]
    assert before=={table:count(service,table) for table in tables}

def test_missing_mapping_retained_then_retry_new_version(env):
    service,entity=env;body=envelope();body.pop('mapping_id');body.pop('mapping_version')
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='needs_mapping' and count(service,'observations')==0
    mutate(service,'register_mapping',mapping(entity,'2'))
    stored=mutate(service,'retry_intake',{'receipt_id':receipt['id'],'mapping_id':'temperature-import','mapping_version':'2'})
    assert stored['status']=='stored',stored['issues']
    assert [a['status'] for a in stored['attempts']]==['needs_mapping','stored']
    assert stored['raw_envelope']==body and stored['raw_evidence_id']==receipt['raw_evidence_id']
    with pytest.raises(DomainError) as error:mutate(service,'retry_intake',{'receipt_id':receipt['id'],'mapping_id':'temperature-import','mapping_version':'2'})
    assert error.value.code=='receipt_already_stored' and count(service,'observations')==1

def test_mapping_immutable_and_source_contract_exact(env):
    service,entity=env;m=mapping(entity)
    first=mutate(service,'register_mapping',m);assert mutate(service,'register_mapping',m)['content_hash']==first['content_hash']
    m['defaults']['method']='changed'
    with pytest.raises(DomainError) as error:mutate(service,'register_mapping',m)
    assert error.value.code=='immutable_mapping'
    body=envelope();body['schema_version']='v2'
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='validation_failed' and receipt['issues'][0]['code']=='mapping_source_mismatch'

@pytest.mark.parametrize('change,code',[
    ({'unit':'K'},'source_unit_mismatch'),
    ({'readings':{}},'missing_source_field'),
    ({'at':'2026-01-01T12:00:00'},'invalid_time'),
    ({'readings':{'temperature':True}},'invalid_decimal_mapping'),
    ({'readings':{'temperature':1000}},'property_value_range'),
])
def test_failed_conversion_keeps_original_without_observation(env,change,code):
    service,entity=env;mutate(service,'register_mapping',mapping(entity));body=envelope();body['payload'].update(change)
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='validation_failed' and receipt['issues'][0]['code']==code,receipt
    assert receipt['raw_envelope']==body and count(service,'evidence')==1 and count(service,'observations')==0

@pytest.mark.parametrize('field,value',[('source_category','unknown'),('record_kind','unknown'),('content_type','image/jpeg')])
def test_unknown_classification_waits_without_guessing(env,field,value):
    service,entity=env;mutate(service,'register_mapping',mapping(entity));body=envelope();body[field]=value
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='needs_mapping' and count(service,'observations')==0
    assert receipt['raw_envelope'][field]==value

def test_tenant_authorization_and_source_dedup_scope(env):
    service,entity=env;body=envelope();receipt=mutate(service,'receive_intake',body)
    other=dict(ACTOR,tenant_id='intake-b')
    assert service.query('intake_receipts','intake-b',other)['items']==[]
    with pytest.raises(DomainError) as error:service.query('intake_receipts','intake-b',other,{'receipt_id':receipt['id']})
    assert error.value.code=='receipt_not_found'
    second=mutate(service,'receive_intake',body,actor=other,tenant='intake-b');assert second['id']!=receipt['id']
    viewer=dict(ACTOR,roles=['viewer'])
    with pytest.raises(DomainError) as error:mutate(service,'receive_intake',body,actor=viewer)
    assert error.value.status==403
    with pytest.raises(DomainError):mutate(service,'register_mapping',mapping(entity),actor=dict(ACTOR,roles=['operator']))

def test_failed_entity_assignment_rolls_back_partial_target(env):
    service,entity=env
    m={'mapping_id':'entity-import','version':'1','source_id':'registry','schema_version':'1','record_kind':'entity','target_action':'create_entity','mode':'identity','source_category':'external_system','content_type':'application/json'}
    mutate(service,'register_mapping',m)
    body={'source_id':'registry','source_record_id':'one','schema_version':'1','source_category':'external_system','content_type':'application/json','record_kind':'entity','mapping_id':'entity-import','mapping_version':'1',
      'payload':{'entity_type':'pond','name':'Must roll back','semantic_types':[{'package_id':'missing','version':'1.0.0','type_id':'unknown'}]}}
    before=count(service,'entities');receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='validation_failed' and count(service,'entities')==before
    assert count(service,'evidence')==1 and count(service,'intake_receipts')==1

def test_model_only_candidate_with_producer_and_input_evidence(env):
    service,entity=env
    evidence=mutate(service,'create_evidence',{'kind':'image','uri':'urn:synthetic:image','content_hash':'a'*64,'source_id':'camera'})
    m={'mapping_id':'external-model','version':'1','source_id':'model-service','schema_version':'1','record_kind':'assertion','target_action':'create_assertion','mode':'identity','source_category':'model','content_type':'application/json'}
    mutate(service,'register_mapping',m)
    body={'source_id':'model-service','source_record_id':'one','schema_version':'1','source_category':'model','content_type':'application/json','record_kind':'assertion','mapping_id':'external-model','mapping_version':'1','producer':{'name':'external-test-model','version':'2026.1'},'evidence_ids':[evidence['id']],
      'payload':{'subject_key':entity['entity_key'],'predicate_id':'water.condition','property_ref':{'package_id':'water','version':'1.0.0','property_id':'water.condition'},'value':{'value':'attention'}}}
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='stored',receipt['issues']
    assert receipt['record']['status']=='candidate' and receipt['record']['origin']=='model'
    assert receipt['raw_envelope']['producer']==body['producer']
    body['source_record_id']='two';body.pop('producer')
    assert mutate(service,'receive_intake',body)['issues'][0]['code']=='model_producer_required'
    body['source_record_id']='three';body['producer']={'name':'m','version':'1'};body.pop('evidence_ids')
    assert mutate(service,'receive_intake',body)['issues'][0]['code']=='model_evidence_required'

def test_bad_evidence_shape_yields_durable_validation_failure(env):
    service,entity=env;m=mapping(entity);m.update(mode='identity');m.pop('field_rules');mutate(service,'register_mapping',m)
    body=envelope();body['payload']={'subject_key':entity['entity_key'],'evidence_ids':'not-an-array'}
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='validation_failed' and receipt['issues'][0]['code']=='invalid_evidence_ids'
    assert count(service,'intake_receipts')==1

def test_mapping_rejects_overlapping_paths_and_reserved_status(env):
    service,entity=env;m=mapping(entity)
    m['field_rules'].append({'source_path':'/x','target_path':'/value'})
    with pytest.raises(DomainError) as error:mutate(service,'register_mapping',m)
    assert error.value.code=='mapping_path_collision'
    m=mapping(entity);m['field_rules'][0]['target_path']='/status'
    with pytest.raises(DomainError) as error:mutate(service,'register_mapping',m)
    assert error.value.code=='reserved_mapping_target'

def test_receipt_list_pagination_and_filter(env):
    service,entity=env
    for i in range(3):
        body=envelope();body['source_record_id']=str(i);mutate(service,'receive_intake',body)
    first=service.query('intake_receipts',TENANT,ACTOR,{'status':'needs_mapping','limit':2})
    assert len(first['items'])==2 and first['truncated']
    second=service.query('intake_receipts',TENANT,ACTOR,{'status':'needs_mapping','limit':2,'offset':2})
    assert len(second['items'])==1 and not second['truncated']
    assert not ({r['id'] for r in first['items']}&{r['id'] for r in second['items']})


@pytest.fixture()
def http(env,tmp_path):
    from agri.app import create_app
    service,entity=env
    app=create_app({'TESTING':True,'SERVICE':service,'DEMO_MODE':False,'AUTH_TOKENS':{
        'admin-intake':ACTOR,'reader-intake':dict(ACTOR,id='reader',roles=['viewer']),
        'other-intake':dict(ACTOR,id='other',tenant_id='intake-other')},'ASSET_ROOT':tmp_path/'assets'})
    return app.test_client(),service,entity

def http_post(client,path,body,token='admin-intake',key=None):
    headers={'Authorization':'Bearer '+token} if token else {}
    if key is not None:headers['Idempotency-Key']=key
    return client.post('/api/v1'+path,json=body,headers=headers)

def test_http_preview_receive_details_retry_and_source_hash(http):
    client,service,entity=http
    body=envelope();body.pop('mapping_id');body.pop('mapping_version')
    before=count(service,'audit_log')
    preview=http_post(client,'/ingestion/preview',body)
    assert preview.status_code==200 and preview.json['data']['status']=='needs_mapping'
    assert count(service,'evidence')==0 and count(service,'audit_log')==before
    response=http_post(client,'/ingestion/receipts',body,key='http-receipt')
    assert response.status_code==200,response.json
    receipt=response.json['data'];assert receipt['status']=='needs_mapping'
    registered=http_post(client,'/ingestion/mappings',mapping(entity),key='http-mapping')
    assert registered.status_code==200,registered.json
    mapped=dict(body,mapping_id='temperature-import',mapping_version='1')
    before={x:count(service,x) for x in ['audit_log','outbox','evidence','observations','idempotency']}
    preview=http_post(client,'/ingestion/preview',mapped)
    assert preview.status_code==200 and preview.json['data']['would_store']
    assert before=={x:count(service,x) for x in before}
    retry=http_post(client,'/ingestion/receipts/'+receipt['id']+'/retry',{'mapping_id':'temperature-import','mapping_version':'1'},key='http-retry')
    assert retry.status_code==200,retry.json
    result=retry.json['data'];assert result['status']=='stored' and len(result['attempts'])==2
    headers={'Authorization':'Bearer admin-intake'}
    detail=client.get('/api/v1/ingestion/receipts/'+receipt['id'],headers=headers)
    assert detail.status_code==200 and detail.json['data']['raw_envelope']==body
    evidence=client.get('/api/v1/evidence/'+receipt['raw_evidence_id'],headers=headers).json['data']
    assert evidence['metadata']['receipt_format']=='intake-receipt/1'
    assert hashlib.sha256(evidence['metadata']['canonical_json'].encode()).hexdigest()==evidence['content_hash']
    assert client.get('/api/v1/ingestion/receipts?status=stored&limit=1',headers=headers).json['data']['items'][0]['id']==receipt['id']
    assert client.get('/api/v1/ingestion/mappings?source_id=sensor-platform',headers=headers).json['data']['items'][0]['definition']['source_category']=='device'

def test_http_authentication_bad_envelope_and_route_identity(http):
    client,service,entity=http;body=envelope()
    assert http_post(client,'/ingestion/preview',body,token=None).status_code==401
    assert http_post(client,'/ingestion/receipts',body,token=None,key='no-auth').status_code==401
    assert http_post(client,'/ingestion/receipts',body,token='reader-intake',key='reader').status_code==403
    assert http_post(client,'/ingestion/receipts',body).status_code==422
    malformed=deepcopy(body);malformed.pop('source_record_id')
    assert http_post(client,'/ingestion/receipts',malformed,key='malformed').status_code==422
    assert count(service,'intake_receipts')==0
    body['record_kind']='unclassified-report'
    accepted=http_post(client,'/ingestion/receipts',body,key='unknown')
    assert accepted.status_code==200 and accepted.json['data']['status']=='needs_mapping'
    receipt=accepted.json['data']
    assert client.get('/api/v1/ingestion/receipts/'+receipt['id'],headers={'Authorization':'Bearer other-intake'}).status_code==404
    mismatch=http_post(client,'/ingestion/receipts/'+receipt['id']+'/retry',{'receipt_id':str(uuid4()),'mapping_id':'x','mapping_version':'1'},key='bad-route')
    assert mismatch.status_code==422 and mismatch.json['error']['code']=='path_payload_mismatch'
    foreign=http_post(client,'/ingestion/receipts/'+receipt['id']+'/retry',{'mapping_id':'x','mapping_version':'1'},token='other-intake',key='foreign')
    assert foreign.status_code==404

def test_mapping_rejects_category_relabeling(env):
    service,entity=env;mutate(service,'register_mapping',mapping(entity))
    body=envelope();body['source_category']='external_system'
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='validation_failed' and receipt['issues'][0]['code']=='mapping_source_mismatch'
    assert receipt['issues'][0]['details']['field']=='source_category'

def test_concurrent_duplicate_source_creates_one_receipt(env):
    from concurrent.futures import ThreadPoolExecutor
    service,entity=env;mutate(service,'register_mapping',mapping(entity));body=envelope()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:mutate(service,'receive_intake',body),range(3)))
    assert len({r['id'] for r in results})==1
    assert count(service,'intake_receipts')==count(service,'intake_attempts')==count(service,'observations')==1

def test_enum_mapping_and_json_pointer_escape(env):
    service,entity=env
    m={'mapping_id':'enum-import','version':'1','source_id':'inspection-api','schema_version':'1','source_category':'external_system','content_type':'application/json','record_kind':'assertion','target_action':'create_assertion','mode':'fields','subject_key':entity['entity_key'],
       'defaults':{'predicate_id':'water.condition','property_ref':{'package_id':'water','version':'1.0.0','property_id':'water.condition'}},
       'field_rules':[{'source_path':'/a~1b/status~0code','target_path':'/value/value','enum_map':{'0':'normal','1':'attention'}}]}
    mutate(service,'register_mapping',m)
    body={'source_id':'inspection-api','source_record_id':'one','schema_version':'1','source_category':'external_system','content_type':'application/json','record_kind':'assertion','mapping_id':'enum-import','mapping_version':'1','payload':{'a/b':{'status~code':1}}}
    receipt=mutate(service,'receive_intake',body)
    assert receipt['status']=='stored' and receipt['record']['value_json']['value']=='attention'
    body['source_record_id']='two';body['payload']['a/b']['status~code']=7
    failed=mutate(service,'receive_intake',body)
    assert failed['status']=='validation_failed' and failed['issues'][0]['code']=='unmapped_enum'


def test_implicit_unit_destination_cannot_be_overwritten(env):
    service,entity=env;m=mapping(entity)
    m['field_rules'].append({'source_path':'/unit','target_path':'/value/unit'})
    with pytest.raises(DomainError) as error:mutate(service,'register_mapping',m)
    assert error.value.code=='mapping_path_collision'


def test_entity_preview_keeps_standard_payload_shape_and_no_identity(env):
    service,entity=env
    mutate(service,'register_mapping',{'mapping_id':'entity-preview','version':'1','source_id':'registry','schema_version':'1','source_category':'external_system','content_type':'application/json','record_kind':'entity','target_action':'create_entity','mode':'identity'})
    body={'source_id':'registry','source_record_id':'preview','schema_version':'1','source_category':'external_system','content_type':'application/json','record_kind':'entity','mapping_id':'entity-preview','mapping_version':'1','payload':{'name':'Preview only','entity_type':'field'}}
    before=count(service,'entities');preview=service.preview_intake(TENANT,ACTOR,body)
    assert preview['would_store'] and preview['normalized_payload']==body['payload']
    assert preview['target_id'] is None and count(service,'entities')==before
