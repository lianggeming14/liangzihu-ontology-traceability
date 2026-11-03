import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from test_drawing_package import package


def implementation():
    assert importlib.util.find_spec('lzo.gis.drawing_semantics_store'), 'semantics store is missing'
    return importlib.import_module('lzo.gis.drawing_semantics_store')


def sealed(bundle):
    bundle=copy.deepcopy(bundle)
    bundle.pop('content_sha256',None)
    bundle['content_sha256']=hashlib.sha256(json.dumps(bundle,sort_keys=True,ensure_ascii=False,
        separators=(',', ':'),allow_nan=False).encode()).hexdigest()
    return bundle


def bundle(source):
    return sealed({'schema_version':'drawing-semantics/1','dataset_id':source['dataset_id'],
        'version':'1','source_package_sha256':source['content_sha256'],
        'drawings':[{'id':'pdf-01'}],
        'nodes':[{'id':n,'class_iri':'urn:lzo:Field','label':n,'data_nature':'imported_unverified',
                  'properties':[],'source_drawing_ids':['pdf-01']} for n in ['N1','N2']],
        'edges':[{'subject_id':'N1','predicate_iri':'urn:lzo:adjacent','object_id':'N2',
                  'evidence_ids':['e1'],'derivation':{'status':'candidate'}}],
        'profiles':[{'entity_id':'N1','feature_id':'F1','drawing_id':'pdf-01','kind':'field','label':'F1',
            'paper_metrics':{'perimeter_pt':32},'ground_estimate':None,'scale_scenarios':[],
            'depth':None,'measurement_ids':['M1','M2'],'relations':[]}],
        'measurements':[{'id':'M1','subject_id':'N1','drawing_id':'pdf-01','kind':'depth',
            'value':[.5,.8],'value_original':'0.5-0.8','unit':'m','si_value':None,'si_unit':'m',
            'status':'unverified','source_record':{'text':'range'},'evidence_ids':['e1'],
            'aggregation_policy':'not_additive'},
            {'id':'M2','subject_id':'N1','drawing_id':'pdf-01','kind':'area','value':'1.200',
             'unit':'m2','si_value':'1.200','si_unit':'m2','status':'unverified','source_record':{},
             'evidence_ids':['e2'],'aggregation_policy':'not_additive'}]})


@pytest.fixture
def store(tmp_path):
    from lzo.gis.drawing_store import DrawingStore
    from lzo.gis.drawing_package import seal_package
    engine=create_engine('sqlite:///'+str(tmp_path/'semantics.db'))
    source=seal_package(package())
    spatial=DrawingStore(engine);spatial.initialize_offline();spatial.import_package(source)
    result=implementation().DrawingSemanticsStore(engine)
    result.initialize_offline()
    yield result,source,spatial
    engine.dispose()


def test_import_replay_and_immutable_conflict_are_atomic(store):
    s,source,_=store;b=bundle(source)
    assert s.import_bundle(b)['status']=='imported'
    assert s.import_bundle(b)['status']=='unchanged'
    mutated=copy.deepcopy(b);mutated['profiles'][0]['label']='changed'
    with pytest.raises(ValueError,match='digest'):s.import_bundle(mutated)
    with pytest.raises(ValueError,match='version'):s.import_bundle(sealed(mutated))
    assert s.profile('F1')['item']['label']=='F1'


def test_source_binding_blocks_unknown_and_outdated_source(store):
    s,source,spatial=store;b=bundle(source)
    bad=copy.deepcopy(b);bad['source_package_sha256']='b'*64
    with pytest.raises(ValueError,match='source'):s.import_bundle(sealed(bad))
    s.import_bundle(b)
    from lzo.gis.drawing_package import seal_package
    newer=copy.deepcopy(source);newer['version']=2
    spatial.import_package(seal_package(newer))
    with pytest.raises(implementation().SourcePackageMismatch):s.profile('N1')
    with pytest.raises(ValueError,match='source'):s.import_bundle(b)


def test_measurement_filters_cursor_ranges_and_relationship_payload(store):
    s,source,_=store;s.import_bundle(bundle(source))
    first=s.measurements(subject_id='N1',drawing_id='pdf-01',limit=1)
    assert first['items'][0]['value']==[.5,.8]
    second=s.measurements(subject_id='N1',drawing_id='pdf-01',limit=1,cursor=first['next_cursor'])
    assert second['items'][0]['si_value']=='1.200'
    assert second['next_cursor'] is None
    assert len(s.measurements(kind='depth')['items'])==1
    assert s.profile('N1')['item']['feature_id']=='F1'
    assert s.relationships(subject_id='N1')['items'][0]['object_id']=='N2'
    with pytest.raises(ValueError):s.measurements(kind='area',cursor=first['next_cursor'])
    with pytest.raises(ValueError):s.measurements(limit=True)
    with pytest.raises(LookupError):s.profile('absent')


def test_entity_lookup_returns_nonspatial_objects_without_claiming_core_state(store):
    s,source,_=store;s.import_bundle(bundle(source))
    result=s.entity('N2')
    assert result['item']['class_iri']=='urn:lzo:Field'
    assert result['item']['label']=='N2'
    assert result['formal_core_imported'] is None
    assert result['formal_core_import_status']=='not_checked_by_gis_read_model'
    with pytest.raises(LookupError):s.entity('missing')


@pytest.mark.parametrize('mutation', ['node','edge','profile','measurement','drawing','nonfinite'])
def test_invalid_references_and_nonfinite_payloads_leave_no_dataset(store,mutation):
    s,source,_=store;b=bundle(source)
    if mutation=='node':b['nodes'].append(copy.deepcopy(b['nodes'][0]))
    elif mutation=='edge':b['edges'][0]['object_id']='missing'
    elif mutation=='profile':b['profiles'][0]['measurement_ids']=['missing']
    elif mutation=='measurement':b['measurements'][0]['subject_id']='missing'
    elif mutation=='drawing':b['measurements'][0]['drawing_id']='missing'
    else:b['measurements'][0]['value']=float('nan')
    if mutation!='nonfinite':b=sealed(b)
    with pytest.raises(ValueError):s.import_bundle(b)
    with pytest.raises(LookupError):s.profile('F1')


def test_string_versions_use_import_head_and_replay_never_rolls_back(store):
    s,source,_=store;b=bundle(source);b['version']='9';b=sealed(b);s.import_bundle(b)
    newer=copy.deepcopy(b);newer['version']='10';newer=sealed(newer);s.import_bundle(newer)
    s.import_bundle(b)
    assert s.profile('F1')['version']=='10'


def test_postgresql_contract_uses_jsonb_and_measurement_lookup_indexes():
    m=implementation()
    ddl=str(CreateTable(m.measurements).compile(dialect=postgresql.dialect()))
    assert 'JSONB' in ddl
    indexed={tuple(c.name for c in i.columns) for i in m.measurements.indexes}
    for column in ['kind','subject_id','drawing_id']:
        assert ('dataset_id','version',column,'measurement_id') in indexed


def test_cli_validates_without_import_or_owner_credentials(tmp_path,capsys):
    from lzo.gis.drawing_package import seal_package
    source=seal_package(package());payload=bundle(source)
    path=tmp_path/'bundle.json';path.write_text(json.dumps(payload),encoding='utf-8')
    script=Path(__file__).resolve().parents[3]/'scripts/import_drawing_semantics.py'
    assert script.exists(), 'semantics import CLI missing'
    spec=importlib.util.spec_from_file_location('semantics_cli',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.main(['--bundle',str(path)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='validated_not_imported'
    assert result['source_binding_checked'] is False
