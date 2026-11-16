"""Offline, synthetic publication contract tests. No database is mutated."""
import copy
import gzip
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

NS = 'urn:lzo:cad-gis:v1:'


def module():
    try:
        return importlib.import_module('local_server.spatial_publish')
    except ModuleNotFoundError:
        pytest.fail('CAD publication implementation is missing')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / 'input'
    raw = b'original\x00binary\xff'
    path = root / 'source-files' / 'source.bin'
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    obj = {'id': 'field-1', 'iri': NS+'instance:field-1', 'class_key': 'field', 'class_iri': NS+'class:field',
           'label': 'Synthetic field', 'kind': 'field', 'geometry': {'type': 'Point', 'coordinates': [114, 30]},
           'source_refs': [{'path': 'source.bin', 'row_number': 1}], 'source_record_ids': [NS+'source:1'],
           'attributes': {'depth_m': None, 'computed_measurements': {'area_m2': 1.25}},
           'position_status': 'candidate_approximate', 'nature': 'cad_candidate_unverified', 'layer_id': 'field'}
    public = {k:v for k,v in obj.items() if k not in ('source_record_ids','class_key')}
    doc = {'contract': 'lzo-cad-batch/1', 'namespace': NS, 'batch_id': 'a'*64,
           'source_files': [{'id': 'f1', 'file_id': 'f1', 'path': 'source.bin', 'original_path': 'source-files/source.bin',
                             'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}],
           'source_tables': [{'file_id':'f1','name':'rows','columns':['value'], 'row_count':1}],
           'source_records': [{'id':NS+'source:1','file_id':'f1','table':'rows','row_number':1,
                               'payload': {'value': {'__type__':'bytes','base64':'AP8='}},'status':'accepted','issues':[]}],
           'objects':[obj], 'relations':[], 'quality':{'source_rows_lost':0}, 'counts':{'objects':1,'relations':0},
           'map':{'contract':'lzo-spatial-map/2','crs':{'display_srid':4326},'features':[public],
                  'display_features':[], 'unlocated':[], 'layers':[], 'bounds':[114,30,114,30], 'quality':{}}}
    save(root / 'bundle.json', doc)
    return root / 'bundle.json', doc


@pytest.fixture
def parent(tmp_path):
    root = tmp_path / 'parent'
    old = {'iri':'urn:old:instance:1','class_iri':'urn:old:class:asset','label':'Old asset','outgoing':[]}
    device = {'iri':'urn:latest:instance:d1','class_iri':'urn:latest:class:devices','label':'Synthetic device','nature':'synthetic','outgoing':[]}
    older = {'iri':'urn:historic:instance:d1','class_iri':'urn:historic:class:devices','label':'Historic device','nature':'synthetic','outgoing':[]}
    concepts=[]
    for name,row in [('asset',old),('csv_devices',device),('devices',older)]:
        save(root/'data/classes'/f'{name}.json', {'class_iri':row['class_iri'],'instances':[row]})
        concepts.append({'iri':row['class_iri'],'label':name,'parent_iri':None,'children':[], 'table':name,
                         'instance_count':1,'total_instance_count':1,'instances_path':f'classes/{name}.json'})
    manifest={'contract':'old','concepts':concepts,'counts':{'instances':3,'classes':3,'relations':0,'triples':9,'map_objects':10,'map_layers':3},
              'active_csv_batch':{'namespace':'urn:latest:'},'custom_metadata':{'keep':['everything']},'rdf_graphs':['urn:old:graph:1']}
    save(root/'data/manifest.json',manifest)
    save(root/'data/map-features.json',{'schema_version':1,'layers':[]})
    save(root/'data/relations/old.json',{'retain':True})
    return root, manifest


def test_bundle_preserves_binary_and_refuses_changed_source_before_storage(bundle):
    mod=module(); path,doc=bundle
    assert mod.load_bundle(path)['source_records'][0]['payload']['value']['base64']=='AP8='
    (path.parent/'source-files/source.bin').write_bytes(b'changed')
    with pytest.raises(ValueError,match='source|checksum|hash'):
        mod.load_bundle(path)


def test_composition_retains_legacy_and_current_device_identity(bundle,parent,tmp_path):
    mod=module(); path,doc=bundle; root,manifest=parent
    before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result=mod.compose_navigation(root, manifest, doc, tmp_path/'composed', schema_graph=Graph())
    current=result['manifest']; out=Path(result['data_dir'])
    assert current['counts']['instances']==4
    assert current['counts']['classes']==11
    assert current['custom_metadata']=={'keep':['everything']}
    assert current['counts']['triples']==9
    assert current['counts']['map_objects']==2 and current['counts']['map_layers']==1
    assert current['counts']['legacy_map_objects']==10 and current['counts']['legacy_map_layers']==3
    for name,raw in before.items():
        if name not in ('data/map-features.json','data/manifest.json'):
            assert (out/name).read_bytes()==raw
    assert (out/'data/legacy-map-features.json').read_bytes()==before['data/map-features.json']
    mp=json.loads((out/'data/map-features.json').read_text(encoding='utf-8'))
    assert [(r['iri'],r['geometry'],r['nature']) for r in mp['unlocated']]==[('urn:latest:instance:d1',None,'synthetic')]
    assert 'source_record_ids' not in json.dumps(mp)
    assert result['network']['counts']['instances']==4
    assert all(row['sha256'] for row in result['files'].values())
    mod.verify_files(out,result['files'])
    (out/'data/relations/old.json').write_text('corrupt')
    with pytest.raises(ValueError): mod.verify_files(out,result['files'])


def test_missing_relation_endpoint_is_rejected_before_composition(bundle,parent,tmp_path):
    mod=module(); _,doc=bundle; root,manifest=parent
    doc['relations']=[{'subject':NS+'instance:field-1','predicate':NS+'property:spatiallyWithinCandidate','object':NS+'instance:missing'}]
    with pytest.raises(ValueError,match='endpoint|target'):
        mod.compose_navigation(root,manifest,doc,tmp_path/'bad',schema_graph=Graph())
    assert not (tmp_path/'bad').exists()


def test_rdf_typed_measurement_shacl_and_exact_term_readback(bundle,tmp_path):
    module()
    rdf=importlib.import_module('local_server.spatial_rdf'); _,doc=bundle
    generated=rdf.generate_cad_rdf(doc,tmp_path/'rdf')
    graph=Graph().parse(generated['nt_path'],format='nt')
    assert (URIRef(NS+'instance:field-1'),URIRef(NS+'property:area_m2'),Literal('1.25',datatype=XSD.decimal)) in graph
    assert not list(graph.objects(URIRef(NS+'instance:field-1'),URIRef(NS+'property:depth_m')))
    assert rdf.validate_cad_rdf(doc,graph)['status']=='passed'
    assert rdf.verify_cad_readback(generated,generated['nt_path'])['full_terms_equal']
    graph.set((URIRef(NS+'instance:field-1'),URIRef(NS+'property:area_m2'),Literal('1.25')))
    changed=tmp_path/'changed.nt'; graph.serialize(changed,format='nt',encoding='utf-8')
    with pytest.raises(ValueError): rdf.verify_cad_readback(generated,changed)
    with pytest.raises(ValueError): rdf.validate_cad_rdf(doc,graph)


def test_target_guard_rejects_source_ports_and_missing_target_before_connect():
    mod=module()
    for sqlport,rdfport in [(25449,23059),(25459,23049),(5432,3030)]:
        cfg=SimpleNamespace(sql={'admin_dsn':f'host=127.0.0.1 port={sqlport} dbname=test user=test'},fuseki_url=f'http://127.0.0.1:{rdfport}/test')
        with pytest.raises(ValueError): mod.guard_targets(cfg)


class TransactionConnection:
    def __init__(self,active): self.active=active; self.changed=False
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,query,args=None):
        if 'FOR UPDATE' in query and 'lzo_local.state' in query:
            self.result={'singleton':True,'active_release_id':self.active}
        elif query.startswith('UPDATE'):
            self.changed=True; self.result=None
        else:
            self.result={'id':args[0], 'metadata':{},'job_id':None,'lease_token':None}
        return self
    def fetchone(self): return self.result


def test_parent_compare_swap_checks_locked_active_before_mutation(monkeypatch):
    from local_server.store import Store
    conn=TransactionConnection('00000000-0000-4000-8000-000000000002')
    store=Store(SimpleNamespace(),'admin'); monkeypatch.setattr(store,'connect',lambda:conn)
    with pytest.raises(ValueError,match='active|parent'):
        store.publish_release('00000000-0000-4000-8000-000000000003',expected_active_release_id='00000000-0000-4000-8000-000000000001')
    assert conn.changed is False


def test_complete_row_readback_rejects_binary_json_and_extra_rows():
    mod=module(); expected=[(1,{'nested':[None,False,1.25]},b'\x00\xff')]
    assert mod.compare_full_rows(expected,[(1,{'nested':[None,False,1.25]},memoryview(b'\x00\xff'))],'rows')['status']=='passed'
    for changed in [[(1,{'nested':[None,False,1.25]},b'\x00\xfe')],
                    [(1,{'nested':[None,False,'1.25']},b'\x00\xff')],[],expected+expected]:
        assert mod.compare_full_rows(expected,changed,'rows')['status']=='failed'


def test_source_changed_between_preflight_and_sql_copy_is_refused(bundle):
    mod=module(); path,doc=bundle
    (path.parent/'source-files/source.bin').write_bytes(b'changed later')
    with pytest.raises(ValueError,match='checksum|source'):
        mod._rowsets(doc,path)


def test_retry_snapshot_has_stable_schema_blank_node_identity(bundle,parent,tmp_path):
    from rdflib import BNode
    from rdflib.namespace import OWL,RDFS
    mod=module(); _,doc=bundle; root,manifest=parent
    results=[]
    for name in ('first','different'):
        schema=Graph()
        schema.add((URIRef('urn:old:p'),RDF.type,OWL.ObjectProperty))
        schema.add((URIRef('urn:old:p'),RDFS.range,BNode(name)))
        schema.add((URIRef('urn:old:q'),RDFS.range,BNode(name)))
        results.append(mod.compose_navigation(root,manifest,doc,tmp_path/name,schema_graph=schema))
    assert results[0]['files']==results[1]['files']


def test_geometries_keep_unknown_original_srid_separate_from_display(bundle):
    mod=module(); path,doc=bundle
    doc['source_records'][0].update(geometry={'type':'Point','coordinates':[500000,3300000]},source_srid=-1)
    rows=mod._rowsets(doc,path)['geometries'][1]
    assert [(row[2],row[3],row[4]) for row in rows]==[('original',-1,0),('candidate_display',4326,4326)]
    assert rows[0][5]['coordinates']==[500000,3300000]
    assert rows[1][5]['coordinates']==[114,30]


def test_unknown_original_crs_keeps_declared_srid_evidence_without_assigning_it(bundle):
    mod=module(); path,doc=bundle
    doc['source_records'][0].update(geometry={'type':'Point','coordinates':[500000,3300000]},source_srid=4547,issues=['unknown_crs'])
    row=mod._rowsets(doc,path)['geometries'][1][0]
    assert row[3]==4547 and row[4]==0


def test_existing_partial_rdf_graph_is_never_patched(bundle,tmp_path,monkeypatch):
    import httpx
    rdf=importlib.import_module('local_server.spatial_rdf'); _,doc=bundle
    generated=rdf.generate_cad_rdf(doc,tmp_path/'rdf')
    writes=[]
    def handler(request):
        if request.url.path.endswith('/query'): return httpx.Response(200,json={'boolean':True})
        if request.method=='GET': return httpx.Response(200,content=b'<urn:wrong> <urn:wrong:p> "wrong" .\n')
        writes.append(request); return httpx.Response(200)
    client=httpx.Client
    monkeypatch.setattr(rdf.httpx,'Client',lambda **kwargs:client(transport=httpx.MockTransport(handler),**kwargs))
    with pytest.raises(ValueError,match='RDF readback'):
        rdf.load_cad_rdf(SimpleNamespace(fuseki_url='http://127.0.0.1:23059/test'),generated)
    assert writes==[]


class PublicationStore:
    def __init__(self,base): self.active=base; self.releases={base['release_id']:base}
    def connect(self): return TransactionConnection(self.active['release_id'])
    def active_release(self): return copy.deepcopy(self.active)
    def get_release(self,identifier): return copy.deepcopy(self.releases.get(identifier))
    def register_release(self,details):
        row={**copy.deepcopy(details),'metadata':{k:copy.deepcopy(v) for k,v in details.items() if k!='release_id'}}
        existing=self.releases.get(row['release_id'])
        if existing and existing!=row: raise ValueError('immutable release mismatch')
        self.releases[row['release_id']]=row
        return row
    def publish_release(self,identifier,*,expected_active_release_id):
        if self.active['release_id']!=expected_active_release_id: raise ValueError('active parent changed')
        self.active=self.releases[identifier]
        return self.active


@pytest.fixture
def publication(bundle,parent,tmp_path,monkeypatch):
    mod=module(); root,manifest=parent
    base={'release_id':'00000000-0000-4000-8000-000000000001','path_base':'data',
          'navigation_dir':'parent','manifest_path':'parent/data/manifest.json','counts':manifest['counts'],
          'rdf_graphs':['urn:old:graph:1'],'sql_schemas':['historic'],'data_nature':'mixed_review_data',
          'complete_old_metadata':{'keep':'yes'},'verification':{'legacy':'passed'}}
    store=PublicationStore(base)
    config=SimpleNamespace(data_dir=tmp_path,review_dir=root,sql={'admin_dsn':'host=127.0.0.1 port=25459 dbname=test user=test'},fuseki_url='http://127.0.0.1:23059/test')
    monkeypatch.setattr(mod,'Store',lambda *args:store)
    monkeypatch.setattr(mod,'store_cad_bundle',lambda *args,**kw:{'status':'passed','schema':'cad_'+'a'*24,'all_rows_verified':True})
    def rdf_load(config,generated,**kw):
        import shutil
        from local_server.spatial_rdf import verify_cad_readback
        target=Path(generated['nt_path']).with_name('readback.nt'); shutil.copyfile(generated['nt_path'],target)
        return verify_cad_readback(generated,target)
    monkeypatch.setattr(mod,'load_cad_rdf',rdf_load)
    monkeypatch.setattr(mod,'fetch_published_schema',lambda *args:Graph())
    return mod,config,store,bundle[0]


def test_publication_preserves_graphs_schemas_metadata_and_is_idempotent(publication):
    mod,config,store,path=publication
    result=mod.publish_cad_bundle(config,path)
    assert result['counts']['instances']==4
    assert store.active['rdf_graphs']==['urn:old:graph:1',NS+'graph:'+'a'*64]
    assert store.active['sql_schemas']==['historic','cad_'+'a'*24]
    assert store.active['complete_old_metadata']=={'keep':'yes'}
    assert store.active['data_nature']=='mixed_review_data'
    assert store.active['verification']['legacy']=='passed'
    assert mod.publish_cad_bundle(config,path)['release_id']==result['release_id']
    assert len(store.releases)==2
    doc=json.loads(path.read_text(encoding='utf-8')); doc['quality']['changed']=True; save(path,doc)
    with pytest.raises(ValueError,match='Immutable'): mod.publish_cad_bundle(config,path)
    assert store.active['release_id']==result['release_id']


def test_failed_rdf_stage_keeps_old_active(publication,monkeypatch):
    mod,config,store,path=publication
    def fail(*args,**kwargs): raise ValueError('native RDF fixture failure')
    monkeypatch.setattr(mod,'load_cad_rdf',fail)
    with pytest.raises(ValueError,match='RDF fixture'): mod.publish_cad_bundle(config,path)
    assert store.active['release_id']=='00000000-0000-4000-8000-000000000001'
    assert len(store.releases)==1


def test_concurrent_parent_change_cannot_be_overwritten(publication):
    mod,config,store,path=publication
    def progress(row):
        if row['stage']=='cad_publish': store.active={**store.active,'release_id':'00000000-0000-4000-8000-000000000099'}
    with pytest.raises(ValueError,match='active parent'): mod.publish_cad_bundle(config,path,progress=progress)
    assert store.active['release_id']=='00000000-0000-4000-8000-000000000099'


def test_retry_after_registered_activation_failure_reuses_exact_snapshot(publication,monkeypatch):
    mod,config,store,path=publication
    original=store.publish_release
    def fail(*args,**kwargs): raise ValueError('activation unavailable')
    monkeypatch.setattr(store,'publish_release',fail)
    with pytest.raises(ValueError,match='activation unavailable'): mod.publish_cad_bundle(config,path)
    registered=set(store.releases)
    monkeypatch.setattr(store,'publish_release',original)
    result=mod.publish_cad_bundle(config,path)
    assert set(store.releases)==registered
    assert result['release_id']==store.active['release_id']


def test_rdf_candidate_parent_matches_public_hierarchy(bundle,tmp_path):
    rdf=importlib.import_module('local_server.spatial_rdf'); _,doc=bundle
    generated=rdf.generate_cad_rdf(doc,tmp_path/'rdf',parent_class_iri='urn:old:class:root')
    from rdflib.namespace import RDFS
    graph=Graph().parse(generated['nt_path'],format='nt')
    assert (URIRef(NS+'class:candidate'),RDFS.subClassOf,URIRef('urn:old:class:root')) in graph


def test_rdf_measurements_include_perimeter_and_keep_source_values_distinct(bundle,tmp_path):
    rdf=importlib.import_module('local_server.spatial_rdf'); _,doc=bundle
    doc['objects'][0]['attributes'].update(computed_measurements={'area_m2':12.5,'perimeter_m':15.25,'length_m':8.125,
        'method':'pyproj.Geod WGS84 ellipsoidal geodesic','units':{'area':'m2','length':'m','perimeter':'m'},
        'assumptions':'Candidate coordinates, not field verified'},source_values=[{'measure_type':'area','measure_value':'999','measure_unit':'mu'}])
    generated=rdf.generate_cad_rdf(doc,tmp_path/'rdf')
    graph=Graph().parse(generated['nt_path'],format='nt'); subject=URIRef(NS+'instance:field-1')
    for key,value in [('area_m2','12.5'),('perimeter_m','15.25'),('length_m','8.125')]:
        assert (subject,URIRef(NS+'property:'+key),Literal(value,datatype=XSD.decimal)) in graph
    assert not list(graph.objects(subject,URIRef(NS+'property:depth_m')))
    assert (subject,URIRef(NS+'property:measurementMethod'),Literal('pyproj.Geod WGS84 ellipsoidal geodesic')) in graph
    assert '999' in str(graph.value(subject,URIRef(NS+'property:sourceDeclaredMeasurements')))
    graph.set((subject,URIRef(NS+'property:perimeter_m'),Literal('15.25')))
    with pytest.raises(ValueError,match='SHACL'): rdf.validate_cad_rdf(doc,graph)


def test_browser_shards_backward_relations_and_measurement_fields(bundle,parent,tmp_path):
    mod=module(); _,doc=bundle; root,manifest=parent
    doc['objects'][0]['attributes']['computed_measurements']['perimeter_m']=15.5
    region=copy.deepcopy(doc['objects'][0]); region.update(id='region',iri=NS+'instance:region',class_iri=NS+'class:region',kind='region',class_key='region',geometry=None)
    doc['objects'].append(region)
    doc['map']['unlocated'].append({k:v for k,v in region.items() if k not in ('source_record_ids','class_key')})
    doc['relations']=[{'subject':doc['objects'][0]['iri'],'predicate':NS+'property:sourceDiagramRegion','object':region['iri']}]
    out=mod.compose_navigation(root,manifest,doc,tmp_path/'composed',schema_graph=Graph())
    assert out['manifest']['contract']==manifest['contract']
    field=json.loads((tmp_path/'composed/data/classes/cad_field.json').read_text(encoding='utf-8'))
    assert field['contract']=='fish-rdf-review/1'
    assert 'detail_path' in field['instances'][0]
    detail=json.loads(gzip.decompress((tmp_path/'composed/data'/field['instances'][0]['detail_path']).read_bytes()))
    assert detail['contract']=='fish-rdf-review/1'
    props={r['field']:r for r in detail['instances'][0]['properties'] if 'field' in r}
    assert props['perimeter_m']['value']==15.5 and props['perimeter_m']['unit']=='m'
    assert props['depth_m']['value'] is None
    shard=json.loads((tmp_path/'composed/data/classes/cad_region.json').read_text(encoding='utf-8'))
    region_detail=json.loads(gzip.decompress((tmp_path/'composed/data'/shard['instances'][0]['detail_path']).read_bytes()))
    incoming=region_detail['instances'][0]['incoming'][0]
    assert incoming['source_iri']==doc['objects'][0]['iri']
    assert incoming['source_class_iri']==NS+'class:field'


def test_retained_private_bundle_is_self_contained_and_rejects_mutation(bundle,tmp_path):
    mod=module(); path,doc=bundle
    retained=mod.retain_bundle(path,tmp_path/'private/input')
    assert retained.read_bytes()==path.read_bytes()
    assert (retained.parent/'source-files/source.bin').read_bytes()==b'original\x00binary\xff'
    assert mod.retain_bundle(path,retained.parent)==retained
    (retained.parent/'source-files/source.bin').write_bytes(b'corrupted retained source')
    with pytest.raises(ValueError,match='checksum|source'):
        mod.retain_bundle(path,retained.parent)


def test_release_points_to_retained_private_cad_source(publication):
    mod,config,store,path=publication
    mod.publish_cad_bundle(config,path)
    retained=config.data_dir/store.active['cad_source_path']
    assert retained.is_file() and retained.read_bytes()==path.read_bytes()
    assert not Path(store.active['cad_source_path']).is_absolute()
