"""Persisted manual intake, media provenance, and additive migration checks."""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import sqlite3
import pytest

ACTOR={'id':'field-operator','tenant_id':'field-a','roles':['admin']}

@pytest.fixture()
def intake(tmp_path):
    from agri.sqlite_db import SQLiteDatabase
    from agri.field_service import FieldService
    from agri.app import create_app
    db=SQLiteDatabase('sqlite:///'+str(tmp_path/'intake.db')); db.migrate()
    service=FieldService(db)
    entity=service.mutate('create_entity','field-a',ACTOR,{'entity_type':'field','name':'Intake field'},'entity')
    app=create_app({'TESTING':True,'SERVICE':service,'DEMO_MODE':False,'AUTH_TOKENS':{
        'operator-test':ACTOR,'viewer-test':dict(ACTOR,id='view',roles=['viewer']),
        'other-test':dict(ACTOR,id='other',tenant_id='field-b')},'ASSET_ROOT':tmp_path/'assets'})
    service=app.extensions['agri_service']
    service.mutate('register_package','field-a',ACTOR,{'package_id':'field-test','version':'1.0.0','namespace':'urn:field-test:', 'label':'现场测试本体','types':[{'type_id':'water_field','identity_type':'field','label':'水田'}],'properties':[{'property_id':'water.temperature','label':'水温','applies_to':['water_field'],'value_type':'decimal','unit':'Cel','usage':'observation'}]},'package')
    service.mutate('assign_type','field-a',ACTOR,{'entity_key':entity['entity_key'],'package_id':'field-test','version':'1.0.0','type_id':'water_field','valid_from':'2020-01-01T00:00:00Z'},'type')
    return app.test_client(),service,entity,tmp_path

def post(client,path,body,key='form',token='operator-test'):
    return client.post('/api/v1'+path,json=body,headers={'Authorization':'Bearer '+token,'Idempotency-Key':key})

def observation(entity):
    return {'record_kind':'observation','note':'人工仪表读数，记录员填报','payload':{
        'subject_key':entity['entity_key'],'property_id':'water.temperature',
        'value':{'value':'22.5','unit':'Cel'},'observed_at':'2026-10-10T08:00:00+08:00',
        'method':'handheld meter','origin':'measured'}}

def test_manual_original_evidence_record_and_idempotency(intake):
    client,service,entity,_=intake
    body=observation(entity)
    first=post(client,'/ingestion/manual',body)
    assert first.status_code==200,first.json
    data=first.json['data'];ev=data['evidence'];record=data['record']
    assert record['origin']=='reported'
    assert record['evidence_ids']==[ev['id']]
    assert ev['metadata']['receipt']['envelope']==body
    assert hashlib.sha256(ev['metadata']['canonical_json'].encode()).hexdigest()==ev['content_hash']
    assert post(client,'/ingestion/manual',body).json['data']==data
    body['note']='changed note'
    assert post(client,'/ingestion/manual',body).status_code==409
    with service.db.transaction() as tx:
        assert tx.execute('SELECT COUNT(*) AS n FROM evidence').fetchone()['n']==1
        assert tx.execute('SELECT COUNT(*) AS n FROM observations').fetchone()['n']==1
        assert tx.execute('SELECT COUNT(*) AS n FROM audit_log WHERE action=%s',('ingest_manual',)).fetchone()['n']==1

def test_manual_bad_reference_rolls_back_evidence_and_reusable_key(intake):
    client,service,entity,_=intake
    body=observation(entity);body['payload']['subject_key']='00000000-0000-4000-8000-000000000001'
    assert post(client,'/ingestion/manual',body).status_code==404
    with service.db.transaction() as tx:
        assert tx.execute('SELECT COUNT(*) AS n FROM evidence').fetchone()['n']==0
    assert post(client,'/ingestion/manual',observation(entity)).status_code==200
    assert post(client,'/ingestion/manual',observation(entity),'v',token='viewer-test').status_code==403
    assert post(client,'/ingestion/manual',observation(entity),'o',token='other-test').status_code==404

@pytest.mark.parametrize('event_type',['inspection','irrigation','maintenance','incident'])
def test_field_events_link_entities_without_inventory_mutation(intake,event_type):
    client,service,entity,_=intake
    body={'record_kind':'event','note':'现场记录','payload':{'event_type':event_type,
        'occurred_at':'2026-10-10T08:00:00Z','participants':[{'entity_key':entity['entity_key'],'role':'location'}],
        'metadata':{'note':'synthetic field event'}}}
    response=post(client,'/ingestion/manual',body)
    assert response.status_code==200,response.json
    assert response.json['data']['record']['event_payload']['field_record'] is True
    with service.db.transaction() as tx:
        assert tx.execute('SELECT COUNT(*) AS n FROM event_participants').fetchone()['n']==1
        assert tx.execute('SELECT COUNT(*) AS n FROM material_ancestry').fetchone()['n']==0
    body['payload']['inputs']=[]
    assert post(client,'/ingestion/manual',body,'bad-quantity').status_code==422

def image_bytes():
    from PIL import Image
    out=BytesIO();Image.new('RGB',(96,64),(16,32,48)).save(out,format='PNG');return out.getvalue()

def upload(client,content,kind='image',key='asset',filename='capture.png'):
    return client.post('/api/v1/ingestion/assets',data={'file':(BytesIO(content),filename),'source_kind':kind,'source_id':'camera:test'},headers={'Authorization':'Bearer operator-test','Idempotency-Key':key})

def test_image_original_integrity_is_independent_of_external_analysis(intake):
    client,service,entity,tmp=intake
    original=image_bytes();response=upload(client,original)
    assert response.status_code==200,response.json
    ev=response.json['data'];meta=ev['metadata']
    assert meta['processing']['status']=='not_requested'
    assert meta['carrier']['format_status']=='verified_structure'
    assert meta['carrier']['width']==96
    assert meta['carrier']['content_analysis']=='not_performed'
    assert ev['content_hash']==hashlib.sha256(original).hexdigest()
    path='/api/v1/evidence/'+ev['id']+'/asset'
    assert client.get(path).status_code==401
    assert client.get(path,headers={'Authorization':'Bearer other-test'}).status_code==404
    original_response=client.get(path,headers={'Authorization':'Bearer operator-test'})
    assert original_response.status_code==200 and original_response.data==original
    assert service._availability('field-a',ev)=='verified'
    assert upload(client,original).json['data']==ev
    assert client.get('/api/v1/evidence/'+ev['id']+'/preview',headers={'Authorization':'Bearer operator-test'}).status_code==404
    assert not (tmp/'assets'/'derived').exists()
    assert post(client,'/evidence/withdrawals',{'evidence_id':ev['id'],'reason':'synthetic withdrawal'},'withdraw').status_code==200
    assert client.get(path,headers={'Authorization':'Bearer operator-test'}).status_code==409

def test_bad_image_keeps_raw_with_carrier_mismatch(intake):
    client,service,_,_=intake
    ev=upload(client,b'not an image').json['data']
    assert ev['metadata']['processing']['status']=='not_requested'
    assert ev['metadata']['carrier']['classification_status']=='needs_mapping'
    assert ev['content_hash']==hashlib.sha256(b'not an image').hexdigest()
    assert service._availability('field-a',ev)=='verified'
    assert service._evidence_checks('field-a',ev)['carrier_status']=='mismatch'

def test_video_header_is_not_claimed_decoded_or_analyzed(intake):
    client,service,_,_=intake
    ev=upload(client,b'\x00\x00\x00\x18ftypisom'+b'0'*20,'video',filename='sample.mp4').json['data']
    assert ev['metadata']['processing']['status']=='not_requested'
    assert ev['metadata']['carrier']['format_status']=='recognized_header'
    assert ev['metadata']['carrier']['decode_status']=='not_checked'
    assert ev['metadata']['carrier']['content_analysis']=='not_performed'
    assert service._availability('field-a',ev)=='verified'

def test_existing_001_database_upgrade_preserves_records(tmp_path):
    from agri.sqlite_db import SQLiteDatabase, _statements
    db=SQLiteDatabase('sqlite:///'+str(tmp_path/'old.db'))
    content=(Path(__file__).resolve().parents[1]/'migrations'/'001_core.sqlite.sql').read_text(encoding='utf-8')
    conn=db._connect()
    conn.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    for statement in _statements(content):conn.execute(statement)
    conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES (?,?)',('001',hashlib.sha256(content.encode()).hexdigest()))
    conn.execute('INSERT INTO entities(tenant_id,entity_key,entity_type,entity_id,name,attributes,revision,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?)',('old','a','field','b','old field','{}',1,'2026-01-01','legacy'))
    conn.close()
    assert '002' in db.migrate()['applied_versions']
    assert db.migrate()['applied'] is False
    with db.transaction() as tx:
        assert tx.execute('SELECT name FROM entities WHERE tenant_id=%s',('old',)).fetchone()['name']=='old field'
        assert tx.execute('SELECT COUNT(*) AS n FROM schema_migrations').fetchone()['n']>=2


def test_camera_http_chain_from_plan_to_evidence_and_network(intake):
    client,service,entity,_=intake
    device=post(client,'/devices',{'name':'Camera 01','device_kind':'camera','source_id':'farm-platform','external_device_id':'cam-01','bound_entity_key':entity['entity_key']},'device').json['data']
    policy=post(client,'/device-policies',{'device_id':device['id'],'name':'Daily capture','record_type':'camera_snapshot','start_at':'2026-10-10T00:00:00Z','interval_seconds':600},'policy')
    assert policy.status_code==200,policy.json
    policy=policy.json['data']
    header={'Authorization':'Bearer operator-test'}
    query='/api/v1/device-captures/due?device_id='+device['id']+'&since=2026-10-10T00:00:00Z&as_of=2026-10-10T00:00:00Z'
    slots=client.get(query,headers=header).json['data']['items'];assert len(slots)==1
    ev=upload(client,image_bytes()).json['data']
    record=post(client,'/device-records',{'device_id':device['id'],'source_record_id':'platform:event:1','record_type':'camera_snapshot','captured_at':'2026-10-10T00:00:03Z','data':{},'evidence_ids':[ev['id']],'policy_id':policy['id'],'slot_at':slots[0]['slot_at']},'receipt')
    assert record.status_code==200,record.json
    assert not client.get(query,headers=header).json['data']['items']
    graph=client.get('/api/v1/ontology/graph?center='+entity['entity_key']+'&depth=4',headers=header).json['data']
    assert any(x['kind']=='device_record' for x in graph['nodes'])
    assert any(x['id']=='evidence:'+ev['id'] for x in graph['nodes'])
    assert any(x['predicate']=='registered_at_object' for x in graph['edges'])
    assert not graph['truncated']
    status=post(client,'/device-policies/'+policy['id']+'/status',{'enabled':False},'pause')
    assert status.status_code==200,status.json
    assert post(client,'/devices',{'name':'Hidden','device_kind':'gate','source_id':'x','external_device_id':'1','bound_entity_key':entity['entity_key']},'viewer',token='viewer-test').status_code==403


def test_contract_lists_new_routes_and_resolves_all_schema_refs(intake):
    client,_,_,_=intake
    contract=client.get('/api/v1/openapi.json').json
    for path in ['/api/v1/devices','/api/v1/device-records','/api/v1/device-captures/due','/api/v1/ingestion/manual','/api/v1/evidence/{evidence_id}/preview']:
        assert path in contract['paths']
    def walk(value):
        if isinstance(value,dict):
            if '$ref' in value and value['$ref'].startswith('#/components/schemas/'):
                assert value['$ref'].split('/')[-1] in contract['components']['schemas']
            for item in value.values():walk(item)
        if isinstance(value,list):
            for item in value:walk(item)
    walk(contract)


def test_real_video_decode_when_ffmpeg_is_configured(tmp_path):
    import os
    import subprocess
    executable=os.environ.get('FFMPEG_BIN','')
    if not executable or not Path(executable).is_file():
        pytest.skip('Real video decode UNVERIFIED: FFMPEG_BIN not configured')
    from agri.media import inspect_media
    source=tmp_path/'synthetic.mp4'
    subprocess.run([executable,'-nostdin','-loglevel','error','-f','lavfi','-i','color=c=green:s=64x48:r=2:d=3','-c:v','mpeg4',str(source)],check=True,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    result=inspect_media(source,'video',tmp_path/'derived',interval_seconds=1,max_frames=3)
    assert result['status']=='processed',result
    assert 1<=len(result['frames'])<=3
    assert all((tmp_path/'derived'/frame['preview_hash']).is_file() for frame in result['frames'])


@pytest.mark.parametrize('kind',['observation','event'])
def test_manual_actual_records_reject_future_occurrence(intake,kind):
    client,service,entity,_=intake
    body=observation(entity)
    if kind=='observation': body['payload']['observed_at']='2999-01-01T00:00:00Z'
    else:
        body={'record_kind':'event','payload':{'event_type':'irrigation','occurred_at':'2999-01-01T00:00:00Z','participants':[{'entity_key':entity['entity_key'],'role':'location'}]}}
    response=post(client,'/ingestion/manual',body)
    assert response.status_code==422,response.json
    with service.db.transaction() as tx:
        assert tx.execute('SELECT COUNT(*) AS n FROM evidence').fetchone()['n']==0
