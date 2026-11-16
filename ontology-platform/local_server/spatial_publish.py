"""Append-only CAD SQL/RDF publication over an immutable complete parent.

Only the final Store compare-and-swap changes the active release. Every earlier
write is scoped to this content-addressed batch or a new private snapshot.
"""
from __future__ import annotations

import base64
import copy
import gzip
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .config import contained_path
from .importer import canonical_hash, file_hash
from .network import write_network
from .query import checked_iri, release_path
from .rdf import save_json, verify_files
from .spatial_rdf import NS, C, LABELS, RELATIONS, V, generate_cad_rdf, load_cad_rdf, validate_cad_rdf, vocabulary
from .store import Store
from .worker import _physical


def guard_targets(config):
    try:
        target=conninfo_to_dict(config.sql['admin_dsn'])
        valid=(target.get('port')=='25459' and target.get('host') in ('127.0.0.1','localhost')
               and target.get('dbname') and not target.get('service')
               and urlsplit(config.fuseki_url).port==23059
               and urlsplit(config.fuseki_url).hostname in ('127.0.0.1','localhost'))
    except (KeyError,ValueError): valid=False
    if not valid: raise ValueError('CAD writes require explicit new deployment SQL/RDF targets')


def _validate_bundle(bundle):
    if bundle.get('contract')!='lzo-cad-batch/1' or bundle.get('namespace')!=NS or not re.fullmatch('[a-f0-9]{64}',bundle.get('batch_id','')):
        raise ValueError('Invalid CAD bundle identity')
    objects={row['iri']:row for row in bundle['objects']}
    if len(objects)!=len(bundle['objects']): raise ValueError('Duplicate CAD object identity')
    sources={row['id'] for row in bundle['source_records']}
    if len(sources)!=len(bundle['source_records']): raise ValueError('Duplicate CAD source record identity')
    for iri,row in objects.items():
        if (not checked_iri(iri).startswith(NS+'instance:') or row.get('kind') not in LABELS or row.get('kind')=='candidate'
                or row['class_iri']!=str(C[row['kind']])): raise ValueError('Invalid CAD class or object namespace')
        if any(source not in sources for source in row.get('source_record_ids',[])): raise ValueError('CAD source endpoint missing')
    for row in bundle['relations']:
        if row['subject'] not in objects or row['object'] not in objects: raise ValueError('CAD relation endpoint missing')
        if row['predicate'] not in {str(V[key]) for key in RELATIONS}: raise ValueError('Unreviewed CAD relation predicate')
    public=bundle['map']
    if public.get('contract')!='lzo-spatial-map/2': raise ValueError('Invalid CAD public map')
    mapped=public.get('features',[])+public.get('unlocated',[])
    if len(mapped)!=len(objects) or {row['iri'] for row in mapped}!=set(objects): raise ValueError('CAD map object coverage differs')
    if any('source_record_ids' in row for row in mapped): raise ValueError('Private source identifiers in public map')


def load_bundle(path):
    path=Path(path).resolve()
    bundle=json.loads(path.read_text(encoding='utf-8'))
    _validate_bundle(bundle)
    names=set()
    for row in bundle['source_files']:
        name=row['original_path']
        if name in names: raise ValueError('Duplicate source file')
        names.add(name)
        original=contained_path(path.parent,name)
        if not original.is_file() or original.stat().st_size!=row['size_bytes'] or file_hash(original)!=row['sha256']:
            raise ValueError('CAD source checksum mismatch')
    return bundle


def retain_bundle(bundle_path,destination):
    """Keep a self-contained immutable private input for backup and replay."""
    bundle_path=Path(bundle_path).resolve(); destination=Path(destination).resolve()
    bundle=load_bundle(bundle_path); bundle_bytes=bundle_path.read_bytes()
    retained=destination/'bundle.json'
    if destination.exists():
        if not retained.is_file() or retained.read_bytes()!=bundle_bytes:
            raise ValueError('Immutable retained CAD bundle content differs')
        load_bundle(retained)
        return retained
    staging=destination.with_name(destination.name+'.staging-'+str(uuid4()))
    staging.mkdir(parents=True)
    for row in bundle['source_files']:
        raw=contained_path(bundle_path.parent,row['original_path']).read_bytes()
        if len(raw)!=row['size_bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:
            raise ValueError('CAD source checksum changed during retention')
        target=contained_path(staging,row['original_path']); target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    (staging/'bundle.json').write_bytes(bundle_bytes)
    if canonical_hash(load_bundle(staging/'bundle.json'))!=canonical_hash(bundle):
        raise ValueError('Retained CAD source bundle identity differs')
    staging.rename(destination)
    return retained


def _geometries(bundle):
    from shapely.geometry import shape
    from shapely import wkb
    rows=[]
    def add(owner,role,geometry,srid,details,unknown_crs=False):
        # Original GeoJSON and original bytes stay intact even for invalid shapes.
        # Unknown/negative SRID is represented as PostGIS 0, never guessed 4547.
        declared=srid if isinstance(srid,int) else None
        stored=declared if declared and declared>0 and not unknown_crs else 0
        try: binary=wkb.dumps(shape(geometry),srid=stored,big_endian=False)
        except Exception: binary=None
        rows.append((len(rows)+1,owner,role,declared,stored,geometry,details,binary))
    for row in bundle['source_records']:
        geometries=row.get('geometries') or ([{'geometry':row['geometry'],'source_srid':row.get('source_srid')}] if row.get('geometry') else [])
        for geometry in geometries:
            unknown='unknown_crs' in row.get('issues',[]) or (isinstance(row.get('payload'),dict) and str(row['payload'].get('crs_status','')).upper()=='UNKNOWN')
            add(row['id'],'original',geometry['geometry'],geometry.get('source_srid'),{**geometry,'crs_status':'UNKNOWN' if unknown else 'source_declared'},unknown)
    for row in bundle['objects']:
        if row.get('geometry') is not None:
            add(row['iri'],'candidate_display',row['geometry'],4326,{'registration_status':'candidate_approximate','original_cad_crs_status':'UNKNOWN'})
    return rows


def _rowsets(bundle,bundle_path):
    files=[]
    for i,row in enumerate(bundle['source_files'],1):
        raw=contained_path(Path(bundle_path).parent,row['original_path']).read_bytes()
        if len(raw)!=row['size_bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:
            raise ValueError('CAD source checksum changed before SQL copy')
        files.append((i,row,raw))
    result={'source_files':(['ordinal','document','original_bytes'],files)}
    for name in ('source_tables','source_records','objects','relations'):
        result[name]=(['ordinal','document'],[(i,row) for i,row in enumerate(bundle[name],1)])
    result['geometries']=(['ordinal','owner_iri','role','source_srid','stored_srid','original_geojson','evidence','ewkb'],_geometries(bundle))
    return result


def _portable(value):
    if isinstance(value,(bytes,memoryview)): return {'__binary__':base64.b64encode(bytes(value)).decode('ascii')}
    if isinstance(value,(tuple,list)): return [_portable(item) for item in value]
    if isinstance(value,dict): return {key:_portable(item) for key,item in value.items()}
    return value


def compare_full_rows(expected,actual,label):
    left_hash,right_hash=hashlib.sha256(),hashlib.sha256(); left_count=right_count=mismatch=0
    sentinel=object()
    for left,right in zip_longest(expected,actual,fillvalue=sentinel):
        a=b=None
        if left is not sentinel:
            a=json.dumps(_portable(left),sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(); left_count+=1; left_hash.update(a+b'\n')
        if right is not sentinel:
            b=json.dumps(_portable(right),sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(); right_count+=1; right_hash.update(b+b'\n')
        mismatch+=a!=b
    return {'table':label,'status':'passed' if not mismatch else 'failed','expected_rows':left_count,'actual_rows':right_count,
            'mismatch_rows':mismatch,'expected_sha256':left_hash.hexdigest(),'actual_sha256':right_hash.hexdigest()}


def store_cad_bundle(config,store,bundle,bundle_path,*,progress=None):
    guard_targets(config); _validate_bundle(bundle)
    schema='cad_'+bundle['batch_id'][:24]; emit=progress or (lambda value:None)
    rowsets=_rowsets(bundle,bundle_path)
    identity={'contract':'lzo-cad-sql/1','batch_id':bundle['batch_id'],'bundle_sha256':canonical_hash(bundle),
              'source_files':[{key:row[key] for key in ('id','sha256','size_bytes')} for row in bundle['source_files']],
              'original_srid_policy':'preserved; unknown PostGIS SRID 0','display_srid':4326}
    q=lambda name:sql.SQL('{}.{}').format(sql.Identifier(schema),sql.Identifier(name))
    with store.connect() as connection:
        connection.row_factory=tuple_row
        with connection.transaction():
            target=connection.execute('SELECT inet_server_port(),current_database()').fetchone()
            expected=conninfo_to_dict(config.sql['admin_dsn'])
            if target!=(25459,expected['dbname']): raise ValueError('Actual CAD SQL target differs')
            connection.execute('SELECT pg_advisory_xact_lock(%s)',(int(bundle['batch_id'][:15],16),))
            exists=connection.execute('SELECT to_regnamespace(%s)',(schema,)).fetchone()[0] is not None
            if not exists:
                if not connection.execute("SELECT 1 FROM pg_extension WHERE extname='postgis'").fetchone():
                    raise ValueError('CAD SQL target lacks PostGIS')
                connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
                definitions={'metadata':'key text PRIMARY KEY,document jsonb NOT NULL',
                    'source_files':'ordinal bigint PRIMARY KEY,document jsonb NOT NULL,original_bytes bytea NOT NULL',
                    'source_tables':'ordinal bigint PRIMARY KEY,document jsonb NOT NULL',
                    'source_records':'ordinal bigint PRIMARY KEY,document jsonb NOT NULL',
                    'objects':'ordinal bigint PRIMARY KEY,document jsonb NOT NULL',
                    'relations':'ordinal bigint PRIMARY KEY,document jsonb NOT NULL',
                    'geometries':'ordinal bigint PRIMARY KEY,owner_iri text NOT NULL,role text NOT NULL,source_srid integer,stored_srid integer NOT NULL,original_geojson jsonb NOT NULL,evidence jsonb NOT NULL,ewkb bytea,geometry geometry'}
                for name,definition in definitions.items():
                    connection.execute(sql.SQL('CREATE TABLE {} ({})').format(q(name),sql.SQL(definition)))
                for name,(fields,rows) in rowsets.items():
                    with connection.cursor() as cursor:
                        with cursor.copy(sql.SQL('COPY {} ({}) FROM STDIN').format(q(name),sql.SQL(',').join(map(sql.Identifier,fields)))) as copier:
                            for row in rows: copier.write_row(tuple(Jsonb(value) if isinstance(value,(dict,list)) else value for value in row))
                    emit({'stage':'sql_copy','table':name,'rows':len(rows)})
                connection.execute(sql.SQL('UPDATE {} SET geometry=ST_GeomFromEWKB(ewkb) WHERE ewkb IS NOT NULL').format(q('geometries')))
                identity['physical_sha256']=_physical(connection,schema)
                connection.execute(sql.SQL('INSERT INTO {} VALUES(%s,%s)').format(q('metadata')),('batch',Jsonb(identity)))
                connection.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
                connection.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
            stored=connection.execute(sql.SQL('SELECT key,document FROM {} ORDER BY key').format(q('metadata'))).fetchall()
            if len(stored)!=1 or stored[0][0]!='batch' or any(stored[0][1].get(k)!=v for k,v in identity.items()):
                raise ValueError('Existing CAD SQL identity differs; refusing overwrite')
            if _physical(connection,schema)!=stored[0][1].get('physical_sha256'): raise ValueError('CAD SQL physical schema changed')
            checks=[]
            for number,(name,(fields,expected_rows)) in enumerate(rowsets.items()):
                with connection.cursor(name='cad_verify_'+str(number)) as cursor:
                    cursor.itersize=1000
                    cursor.execute(sql.SQL('SELECT {} FROM {} ORDER BY ordinal').format(sql.SQL(',').join(map(sql.Identifier,fields)),q(name)))
                    checks.append(compare_full_rows(expected_rows,cursor,name))
                emit({'stage':'sql_readback','table':name,'status':checks[-1]['status']})
            geometry_expected=[(row[0],row[4] if row[-1] is not None else None,row[-1]) for row in rowsets['geometries'][1]]
            actual=connection.execute(sql.SQL("SELECT ordinal,ST_SRID(geometry),ST_AsEWKB(geometry,'NDR') FROM {} ORDER BY ordinal").format(q('geometries')))
            checks.append(compare_full_rows(geometry_expected,actual,'postgis_geometry'))
            if any(check['status']!='passed' for check in checks): raise ValueError('Full CAD SQL readback differs; refusing repair')
    return {'status':'passed','schema':schema,'identity':stored[0][1],'all_rows_verified':True,'checks':checks}


def _read_json(path):
    raw=Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if Path(path).suffix=='.gz' else raw)


def _inventory(directory,exclude=()):
    root=Path(directory)
    return {path.relative_to(root).as_posix():{'bytes':path.stat().st_size,'sha256':file_hash(path)}
            for path in sorted(root.rglob('*')) if path.is_file() and path.relative_to(root).as_posix() not in exclude}


def _latest_devices(directory,manifest):
    classes=[row for row in manifest['concepts'] if row['iri'].endswith('class:devices') and row.get('instances_path')]
    active=manifest.get('active_csv_batch')
    if isinstance(active,dict): namespace=active.get('namespace')
    else: namespace='urn:lzo:csv-batch:v1:'+active+':' if isinstance(active,str) else None
    chosen=[row for row in classes if namespace and row['iri'].startswith(namespace)]
    if not chosen: chosen=[row for row in classes if row.get('table')=='csv_devices'] or classes[-1:]
    devices={}
    for concept in chosen:
        path=contained_path(Path(directory)/'data',concept['instances_path'])
        for row in _read_json(path)['instances']:
            devices[row['iri']]={'id':row.get('id',row['iri']),'iri':row['iri'],'class_iri':row['class_iri'],
                'label':row.get('label',row['iri']),'kind':'device','geometry':None,'source_refs':[],
                'attributes':{'position_basis':'No verified device location supplied'},'position_status':'unlocated',
                'nature':'synthetic','layer_id':'device'}
    return list(devices.values())


def compose_navigation(parent_dir,parent_manifest,bundle,destination,*,schema_graph):
    _validate_bundle(bundle)
    if schema_graph is None: raise ValueError('Actual published RDF schema is required')
    parent_dir=Path(parent_dir).resolve(); destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('Composite destination already exists')
    manifest=copy.deepcopy(parent_manifest)
    concepts={row['iri']:row for row in manifest['concepts']}
    if any(str(C[key]) in concepts for key in LABELS): raise ValueError('CAD classes collide with published parent')
    # Validate old references before copying; never follow an escaping symlink.
    for path in parent_dir.rglob('*'):
        if not path.resolve().is_relative_to(parent_dir): raise ValueError('Parent navigation path escapes snapshot')
    shutil.copytree(parent_dir,destination)
    data=destination/'data'; data.mkdir(exist_ok=True)
    old_map=data/'map-features.json'
    if old_map.exists():
        if (data/'legacy-map-features.json').exists(): raise ValueError('Legacy map destination collision')
        shutil.copyfile(old_map,data/'legacy-map-features.json')
    grouped={key:[] for key in LABELS}
    objects={row['iri']:row for row in bundle['objects']}
    outgoing={iri:[] for iri in objects}; incoming={iri:[] for iri in objects}
    for relation in bundle['relations']:
        predicate=relation['predicate']; target=objects[relation['object']]; source=objects[relation['subject']]
        common={'predicate':predicate,'label':RELATIONS[predicate.rsplit(':',1)[-1]],'resolution':'resolved',
                'edge_iri':NS+'relation:'+canonical_hash(relation),'nature':'cad_candidate_unverified','evidence':relation.get('evidence',{})}
        outgoing[source['iri']].append({**common,'direction':'outgoing','target_iri':target['iri'],'target_label':target['label'],'target_class_iri':target['class_iri']})
        incoming[target['iri']].append({**common,'direction':'incoming','source_iri':source['iri'],'source_label':source['label'],'source_class_iri':source['class_iri']})
    for row in bundle['objects']:
        properties=[{'iri':str(V.dataNature),'label':'数据性质','value':row['nature'],'datatype':'http://www.w3.org/2001/XMLSchema#string'},
                    {'iri':str(V.positionStatus),'label':'位置证据状态','value':row['position_status'],'datatype':'http://www.w3.org/2001/XMLSchema#string'},
                    {'iri':str(V.sourceEvidence),'label':'来源证据','value':row.get('source_refs',[]),'datatype':str(RDF.JSON)},
                    {'iri':str(V.attributes),'label':'候选属性','value':row.get('attributes',{}),'datatype':str(RDF.JSON)}]
        attributes=row.get('attributes',{}); measured=attributes.get('computed_measurements',{})
        for field,label,unit in [('area_m2','候选几何计算面积','m²'),('perimeter_m','候选几何计算周长','m'),
                                 ('length_m','候选几何计算长度','m'),('depth_m','深度（未提供实测时为空）','m')]:
            properties.append({'iri':str(V[field]),'field':field,'label':label,'value':measured.get(field,attributes.get(field)),
                'datatype':'http://www.w3.org/2001/XMLSchema#decimal','unit':unit,'nature':'cad_candidate_unverified',
                'evidence':{'method':measured.get('method'),'assumptions':measured.get('assumptions')}})
        for field,label,value in [('measurementMethod','计算方法',measured.get('method')),
                                   ('measurementUnits','计算单位',measured.get('units')),
                                   ('measurementAssumptions','计算条件与不确定性',measured.get('assumptions'))]:
            properties.append({'iri':str(V[field]),'field':field,'label':label,'value':value,'unit':'不适用',
                'datatype':str(RDF.JSON) if isinstance(value,dict) else 'http://www.w3.org/2001/XMLSchema#string','nature':'cad_candidate_unverified'})
        source_measurements=[{key:value for key,value in item.items() if key in ('measure_type','measure_value','measure_unit')}
                             for item in attributes.get('source_values',[]) if any(key in item for key in ('measure_type','measure_value','measure_unit'))]
        if source_measurements:
            properties.append({'iri':str(V.sourceDeclaredMeasurements),'field':'source_declared_measurements',
                'label':'原始来源标注量测（保留来源单位）','value':source_measurements,'datatype':str(RDF.JSON),
                'unit':'见来源 measure_unit','nature':'source_declared_unverified'})
        grouped[row['kind']].append({key:copy.deepcopy(value) for key,value in row.items() if key not in ('source_record_ids','class_key')})
        grouped[row['kind']][-1].update(properties=properties,outgoing=outgoing[row['iri']],incoming=incoming[row['iri']],
                                       outgoing_count=len(outgoing[row['iri']]),incoming_count=len(incoming[row['iri']]))
    root_iri=manifest.get('root_iri')
    for key,label in LABELS.items():
        parent=root_iri if key=='candidate' and root_iri in concepts else (str(C.candidate) if key!='candidate' else None)
        row={'iri':str(C[key]),'label':label,'parent_iri':parent,'children':[],'table':'cad_'+key if key!='candidate' else None,
             'role':'cad_candidate','instance_count':len(grouped[key]),'total_instance_count':len(grouped[key])}
        if key!='candidate':
            row['instances_path']='classes/cad_'+key+'.json'
            path=data/row['instances_path']
            if path.exists(): raise ValueError('CAD class artifact collision')
            summaries=[]
            for start in range(0,len(grouped[key]),250):
                relative=f'details/cad_{key}/{start//250+1:05d}.json.gz'
                detail_path=data/relative; detail_path.parent.mkdir(parents=True,exist_ok=True)
                if detail_path.exists(): raise ValueError('CAD detail artifact collision')
                chunk=grouped[key][start:start+250]
                payload=json.dumps({'contract':'fish-rdf-review/1','class_iri':row['iri'],'instances':chunk},ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')
                detail_path.write_bytes(gzip.compress(payload,mtime=0))
                for detail in chunk:
                    summaries.append({**{field:detail[field] for field in ('iri','id','class_iri','label','nature')},
                                      'detail_path':relative,'adoption_status':'cad_candidate_not_formally_adopted'})
            save_json(path,{'contract':'fish-rdf-review/1','class_iri':row['iri'],'instances':summaries})
        concepts[row['iri']]=row
    for row in concepts.values(): row['children']=[]
    for row in concepts.values():
        if row.get('parent_iri') in concepts: concepts[row['parent_iri']]['children'].append(row['iri'])
    visited=set()
    def total(iri,trail):
        if iri in trail: raise ValueError('Cyclic published class ancestry')
        visited.add(iri); row=concepts[iri]; row['children'].sort()
        row['total_instance_count']=row.get('instance_count',0)+sum(total(child,trail|{iri}) for child in row['children'])
        return row['total_instance_count']
    for iri,row in concepts.items():
        if row.get('parent_iri') not in concepts: total(iri,set())
    if visited!=set(concepts): raise ValueError('Unreachable cyclic class ancestry')
    manifest['concepts']=sorted(concepts.values(),key=lambda row:row['iri'])
    counts=manifest.setdefault('counts',{})
    counts.update(instances=counts.get('instances',0)+len(objects),classes=len(concepts),
                  relations=counts.get('relations',0)+len(bundle['relations']),
                  resolved_relations=counts.get('resolved_relations',0)+len(bundle['relations']),
                  cad_objects=len(objects),cad_relations=len(bundle['relations']))
    spatial_map=copy.deepcopy(bundle['map']); spatial_map['unlocated'].extend(_latest_devices(parent_dir,parent_manifest))
    spatial_map['layers'].append({'id':'device','label':'合成示例设备（未定位）','visible':False})
    spatial_map['legacy_map_path']='data/legacy-map-features.json'
    for key in ('map_objects','map_layers'):
        if key in counts: counts['legacy_'+key]=counts[key]
    counts.update(map_objects=len(spatial_map['features'])+len(spatial_map['unlocated']),map_layers=len(spatial_map['layers']),
                  map_unlocated=len(spatial_map['unlocated']),map_display_features=len(spatial_map['display_features']))
    if 'source_classes' in counts: counts['source_classes']=sum(bool(row.get('table')) for row in concepts.values())
    save_json(data/'map-features.json',spatial_map)
    graph=schema_graph+vocabulary()
    if root_iri in concepts: graph.add((C.candidate,RDFS.subClassOf,URIRef(root_iri)))
    # N-Triples is valid Turtle. Canonical blank-node IDs plus sorted terms
    # guarantee identical public bytes across process/retry schema readbacks.
    from rdflib.compare import to_canonical_graph
    from rdflib import Literal
    from rdflib.plugins.serializers.nt import _quoteLiteral
    canonical=to_canonical_graph(graph)
    lines=[s.n3()+' '+p.n3()+' '+(_quoteLiteral(o) if isinstance(o,Literal) else o.n3())+' .\n' for s,p,o in canonical]
    (destination/'cad-schema.ttl').write_text(''.join(sorted(lines)),encoding='utf-8',newline='\n')
    manifest.update(composite_contract='local-server-composite-navigation/1',raw_payload_public=False,spatial_map_contract='lzo-spatial-map/2')
    manifest.setdefault('cad_batches',[]).append({'batch_id':bundle['batch_id'],'counts':bundle['counts'],
        'data_nature':'cad_candidate_unverified','formal_adoption':False,'quality':bundle['quality']})
    # The map/manifest change intentionally, while old class/detail/relation
    # hashes retain exactly their parent's values.
    manifest['files']=_inventory(destination,('data/manifest.json','manifest.json','data/ontology-network.json'))
    network=write_network(destination,manifest,schema_graph=graph)
    if network['counts']['instances']!=counts['instances']: raise ValueError('Composite instance count differs from full canonical navigation')
    manifest['files']=_inventory(destination,('data/manifest.json','manifest.json'))
    save_json(data/'manifest.json',manifest)
    files=_inventory(destination)
    verify_files(destination,files)
    return {'data_dir':str(destination),'manifest_path':str(data/'manifest.json'),'manifest':manifest,
            'files':files,'counts':counts,'network':network}


def fetch_published_schema(config,graphs):
    if not graphs: raise ValueError('Parent has no published RDF graphs')
    dataset=' '.join('FROM <'+checked_iri(graph)+'>' for graph in graphs)
    query=(f'SELECT DISTINCT ?s ?p ?o {dataset} WHERE {{ '
           '{ ?s a <'+str(OWL.Class)+'> } UNION { ?s a <'+str(OWL.ObjectProperty)+'> } UNION { ?s a <'+str(OWL.DatatypeProperty)+'> } '
           '?s ?p ?o . FILTER(?p IN ('+','.join('<'+str(p)+'>' for p in (RDF.type,RDFS.subClassOf,RDFS.domain,RDFS.range,RDFS.label))+')) } LIMIT 50001')
    with httpx.Client(timeout=600,trust_env=False) as client:
        response=client.post(config.fuseki_url.rstrip('/')+'/query',data={'query':query},headers={'Accept':'application/sparql-results+json'})
        response.raise_for_status(); rows=response.json()['results']['bindings']
    if len(rows)>50000: raise ValueError('Published schema exceeds bounded schema query')
    from rdflib import BNode,Literal
    def term(row):
        if row['type']=='uri': return URIRef(row['value'])
        if row['type']=='bnode': return BNode(row['value'])
        return Literal(row['value'],lang=row.get('xml:lang'),datatype=URIRef(row['datatype']) if row.get('datatype') else None,normalize=False)
    graph=Graph()
    for row in rows: graph.add(tuple(term(row[key]) for key in ('s','p','o')))
    if not graph: raise ValueError('Published RDF schema is empty')
    return graph


def _validate_public_endpoints(directory,manifest,network):
    concepts={row['iri'] for row in manifest['concepts']}
    if any(edge['source'] not in concepts or edge['target'] not in concepts for edge in network['edges']):
        raise ValueError('Ontology network endpoint missing')
    for concept in manifest['concepts']:
        if concept.get('instances_path') and not contained_path(Path(directory)/'data',concept['instances_path']).is_file():
            raise ValueError('Published class endpoint missing')
    return {'status':'passed','classes':len(concepts),'edges':len(network['edges'])}


def publish_cad_bundle(config,bundle_path:Path,*,progress=None):
    guard_targets(config); bundle_path=Path(bundle_path).resolve(); bundle=load_bundle(bundle_path)
    emit=progress or (lambda value:None); store=Store(config,'admin')
    work=contained_path(config.data_dir,'cad-imports',bundle['batch_id']); work.mkdir(parents=True,exist_ok=True)
    identity={'batch_id':bundle['batch_id'],'bundle_sha256':canonical_hash(bundle),'bundle_file_sha256':file_hash(bundle_path)}
    # A transaction-scoped importer lock prevents same-batch graph/file races.
    # It is independent of store_cad_bundle's SQL lock and the final state lock.
    with store.connect() as lock_connection:
        lock_connection.execute('SELECT pg_advisory_xact_lock(%s)',(-int(bundle['batch_id'][:15],16)-1,))
        identity_path=work/'identity.json'
        if identity_path.exists() and _read_json(identity_path)!=identity: raise ValueError('Immutable CAD retry bundle changed')
        if not identity_path.exists(): save_json(identity_path,identity)
        bundle_path=retain_bundle(bundle_path,work/'input')
        bundle=load_bundle(bundle_path)
        parent=store.active_release()
        if parent is None: raise ValueError('CAD publication requires a complete active parent')
        parent_id=parent['release_id']
        # An already active successful retry verifies its existing files and all
        # SQL/RDF rows below, without rebuilding/re-registering a different release.
        already_active=parent.get('cad_batch_id')==bundle['batch_id']
        if already_active:
            if parent.get('cad_bundle_sha256')!=identity['bundle_sha256']: raise ValueError('Active CAD content identity differs')
            parent_id=parent['parent_release_id']; base=store.get_release(parent_id)
            if base is None: raise ValueError('CAD parent release is missing')
        else: base=parent
        parent_dir=release_path(config,base,base['navigation_dir'])
        parent_manifest=_read_json(release_path(config,base,base['manifest_path']))
        expected_files=base.get('navigation',{}).get('files')
        if expected_files: verify_files(parent_dir,expected_files)
        emit({'stage':'cad_sql','objects':len(bundle['objects'])})
        sql_proof=store_cad_bundle(config,store,bundle,bundle_path,progress=emit); save_json(work/'sql-readback.json',sql_proof)
        generated=generate_cad_rdf(bundle,work/'rdf',parent_class_iri=parent_manifest.get('root_iri'))
        emit({'stage':'cad_rdf','triples':generated['triple_count']})
        rdf_proof=load_cad_rdf(config,generated,progress=emit)
        graph=Graph().parse(work/'rdf/readback.nt',format='nt')
        shacl=validate_cad_rdf(bundle,graph)
        save_json(work/'rdf-readback.json',rdf_proof); save_json(work/'shacl.json',shacl)
        if already_active:
            verify_files(release_path(config,parent,parent['navigation_dir']),parent['navigation']['files'])
            if store.active_release()['release_id']!=parent['release_id']: raise ValueError('Active release changed during retry verification')
            return {'release_id':parent['release_id'],'status':'published','idempotent':True,'sql':sql_proof,'rdf':rdf_proof,'shacl':shacl}
        emit({'stage':'cad_composite_navigation'})
        schema=fetch_published_schema(config,base.get('rdf_graphs') or [base['rdf_graph']])
        release_id=str(uuid5(NAMESPACE_URL,'lzo-cad-release:'+parent_id+':'+bundle['batch_id']+':'+identity['bundle_sha256']))
        destination=contained_path(config.data_dir,'releases',release_id)
        staging=work/('public-'+str(uuid4()))
        navigation=compose_navigation(parent_dir,parent_manifest,bundle,staging,schema_graph=schema)
        graphs=list(dict.fromkeys((base.get('rdf_graphs') or [base['rdf_graph']])+[generated['graph_iri']]))
        schemas=list(dict.fromkeys((base.get('sql_schemas') or ([base['sql_schema']] if base.get('sql_schema') else []))+[sql_proof['schema']]))
        manifest=navigation['manifest']; manifest['rdf_graphs']=graphs
        manifest['counts']['triples']=parent_manifest['counts'].get('triples',0)+generated['triple_count']
        manifest['cad_batches'][-1].update(graph_iri=generated['graph_iri'],sql_schema=sql_proof['schema'],shacl=shacl)
        save_json(staging/'data/manifest.json',manifest); navigation['files']=_inventory(staging)
        endpoints=_validate_public_endpoints(staging,manifest,navigation['network'])
        verify_files(staging,navigation['files'])
        if destination.exists():
            if _inventory(destination)!=navigation['files']: raise ValueError('Immutable composite retry snapshot differs')
        else:
            destination.parent.mkdir(parents=True,exist_ok=True); staging.rename(destination)
        reference=lambda path:contained_path(config.data_dir,path).relative_to(Path(config.data_dir).resolve()).as_posix()
        details=copy.deepcopy(base.get('metadata') or {k:v for k,v in base.items() if k not in ('id','release_id','job_id','lease_token','status','created_at','published_at','metadata')})
        details.update(release_id=release_id,parent_release_id=parent_id,cad_batch_id=bundle['batch_id'],cad_bundle_sha256=identity['bundle_sha256'],
            cad_source_path=reference(bundle_path),cad_source_file_sha256=identity['bundle_file_sha256'],
            path_base='data',navigation_dir=reference(destination),manifest_path=reference(destination/'data/manifest.json'),
            navigation={'data_dir':reference(destination),'manifest_path':reference(destination/'data/manifest.json'),'files':navigation['files']},
            counts=manifest['counts'],rdf_graphs=graphs,sql_schemas=schemas,raw_payload_public=False,
            cad_data_nature='cad_candidate_unverified',synthetic_devices_position='unlocated')
        # Keep the complete parent's verification metadata; add this batch proof.
        details.setdefault('verification',{})['cad']={'sql':sql_proof,'rdf':{k:v for k,v in rdf_proof.items() if k!='existing_graph_verified'},
                                                     'shacl':shacl,'files':'passed','endpoints':endpoints}
        registered=store.register_release(details)
        emit({'stage':'cad_publish','release_id':release_id,'parent_release_id':parent_id})
        published=store.publish_release(registered['release_id'],expected_active_release_id=parent_id)
        result={'release_id':published['release_id'],'parent_release_id':parent_id,'status':'published','batch_id':bundle['batch_id'],
                'sql':sql_proof,'rdf':rdf_proof,'shacl':shacl,'counts':manifest['counts'],'files_verified':len(navigation['files'])}
        save_json(work/'publication.json',result)
        return result
