"""Publish verified CSV-derived chunks and atomically activate ontology navigation."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

from rdflib import Graph
from build_csv_rdf import ROOT,RUNTIME,OUTPUT,PACKAGE,NS,CSV_LABELS,CSV_DOMAINS,check_target,ENDPOINT
from fish_rdf_sample import C,uri_factory,role

PAGE=re.compile(r'(?:classes/csv_[a-z0-9_]+\.json\.gz|details/csv_[a-z0-9_]+/\d{5}\.json\.gz|'
    r'relations/csv_[a-z0-9_]+/[a-f0-9-]{36}/(?:incoming|outgoing)-\d{5}\.json\.gz)\Z')


def merge_manifest(base,schema,rdf_report):
    result=json.loads(json.dumps(base));graph=rdf_report['graph_iri'];model=rdf_report['model']
    batches=result.setdefault('csv_batches',[])
    existing=next((item for item in batches if item['package_sha256']==PACKAGE),None)
    if existing:
        if existing['graph_iri']!=graph:raise ValueError('This source package already has another active RDF projection')
        return result
    result.setdefault('legacy_counts',dict(base['counts']))
    result.setdefault('legacy_graphs',list(base['rdf_graphs']))
    concepts={item['iri']:dict(item) for item in result['concepts']};u=uri_factory(NS)
    for table in schema['tables']:
        iri=str(u('class',table));parent=str(C[CSV_DOMAINS.get(table,'ProductionEvent')])
        if iri in concepts or parent not in concepts:raise ValueError('CSV concept collides or has no shared domain parent')
        count=model['tables'][table]['rows']
        record_role=role(table)
        concepts[iri]={'iri':iri,'label':CSV_LABELS.get(table,'CSV · '+table),'parent_iri':parent,
            'children':[],'table':'csv_'+table,'role':record_role,'instance_count':count,
            'total_instance_count':count,'instances_path':'classes/csv_'+table+'.json.gz','batch_id':PACKAGE}
    for item in concepts.values():item['children']=[]
    for item in concepts.values():
        if item['parent_iri']:
            if item['parent_iri'] not in concepts:raise ValueError('Unknown ontology parent')
            concepts[item['parent_iri']]['children'].append(item['iri'])
    seen=set()
    def walk(iri):
        if iri in seen:raise ValueError('Cyclic or repeated ontology concept')
        seen.add(iri);item=concepts[iri];item['children'].sort()
        item['total_instance_count']=item['instance_count']+sum(walk(child) for child in item['children'])
        return item['total_instance_count']
    total=walk(result['root_iri'])
    if seen!=set(concepts):raise ValueError('Unreachable ontology concepts')
    result['concepts']=sorted(concepts.values(),key=lambda item:item['iri'])
    result['rdf_graphs'].append(graph)
    result['counts'].update(instances=total,classes=len(concepts),source_classes=sum(bool(x['table']) for x in concepts.values()),
        triples=result['counts']['triples']+rdf_report['triple_count'],
        relations=result['counts']['relations']+model['relations'],
        resolved_relations=result['counts']['resolved_relations']+model['resolved_relations'],
        csv_instances=model['instances'],csv_rows=model['raw_rows'],csv_tables=len(schema['tables']),csv_fields=model['schema_fields'])
    batches.append({'package_sha256':PACKAGE,'source_repository':'lianggeming14/upload-files',
        'source_commit':'cb9353499b6ede33fa60b3c67e18a983e362ab16','archive_path':'csv.zip',
        'label':'CSV DB-ready 完整批次','graph_iri':graph,'termset_sha256':rdf_report['termset_sha256'],
        'instances':model['instances'],'relations':model['relations'],'schema_fields':model['schema_fields'],
        'source_tables':len(schema['tables']),'data_nature':'rule simulation, weather reanalysis and reused asset catalog',
        'formal_adoption':False,'raw_payload_public':False})
    result.update(active_csv_batch=PACKAGE,checked_at=datetime.now(timezone.utc).isoformat(),
        jena_verified=True,fuseki_readback=True)
    return result


def main():
    directory=ROOT/'docs/fish/ontology-review';data=directory/'data';stage=RUNTIME/'public'
    read=lambda name:json.loads((OUTPUT/name).read_text(encoding='utf-8'))
    rdf=read('rdf-readback.json');pg=read('pg-readback.json');prior=read('prior-graphs-readback.json');shacl=read('shacl-readback.json')
    if any(item.get('status')!='passed' for item in (rdf,pg,prior,shacl)):raise ValueError('An actual store/readback prerequisite did not pass')
    check_target(ENDPOINT,rdf['graph_iri'])
    if (rdf.get('full_terms_equal') is not True or rdf.get('package_sha256')!=PACKAGE or pg.get('package_sha256')!=PACKAGE
            or pg.get('raw_rows_checked')!=153862 or pg.get('nodes_checked')!=153862 or pg.get('relations_checked')!=810934
            or shacl.get('instances_validated')!=153862 or shacl.get('datatype_constraints')!=1397 or shacl.get('violations')!=0
            or prior.get('csv_source_archive_sha256')!=PACKAGE or len(prior.get('graphs',[]))!=4
            or any(item.get('status')!='passed' for item in prior['graphs']) or prior.get('errors')):
        raise ValueError('CSV reception, RDF constraints or old-graph protection is incomplete')
    schema=json.loads((stage/'model-schema.json').read_text(encoding='utf-8'))
    manifest_path=data/'manifest.json';base=json.loads(manifest_path.read_text(encoding='utf-8'))
    before_path=RUNTIME/'prior-manifest.json'
    if not before_path.exists():
        if base.get('csv_batches'):raise ValueError('Original review manifest was not captured')
        before_path.write_bytes(manifest_path.read_bytes())
    baseline=json.loads(before_path.read_text(encoding='utf-8'))
    if {item['graph_iri'] for item in prior['graphs']}!=set(baseline['rdf_graphs']):raise ValueError('Protected prior graphs differ from original navigation')
    merged=merge_manifest(base,schema,rdf)
    files=read('navigation-files.json')['files'];total=0
    for name,entry in files.items():
        if not PAGE.fullmatch(name):raise ValueError('Unapproved public CSV data path')
        source=(stage/'data'/name).resolve();target=(data/name).resolve()
        if not source.is_relative_to((stage/'data').resolve()) or not target.is_relative_to(data.resolve()):raise ValueError('Public data path escapes')
        payload=source.read_bytes()
        if len(payload)!=entry['bytes'] or hashlib.sha256(payload).hexdigest()!=entry['sha256']:raise ValueError('Staged CSV snapshot changed after verification')
        target.parent.mkdir(parents=True,exist_ok=True)
        pending=target.with_suffix(target.suffix+'.pending')
        pending.write_bytes(payload);pending.replace(target);total+=len(payload)
    for current,addition in [('vocabulary.ttl','csv-vocabulary.ttl'),('shapes.ttl','csv-shapes.ttl')]:
        graph=Graph().parse(directory/current,format='turtle')
        graph+=Graph().parse(stage/addition,format='turtle')
        pending=(directory/current).with_suffix('.ttl.pending')
        pending.write_bytes((graph.serialize(format='turtle').rstrip()+'\n').encode('utf-8'));pending.replace(directory/current)
    pending=manifest_path.with_suffix('.json.pending')
    pending.write_bytes((json.dumps(merged,ensure_ascii=False,indent=2)+'\n').encode('utf-8'));pending.replace(manifest_path)
    report={'contract':'csv-navigation-activation/1','status':'passed','package_sha256':PACKAGE,
        'prior_manifest_sha256':hashlib.sha256(before_path.read_bytes()).hexdigest(),'graph_iri':rdf['graph_iri'],
        'published_data_files':len(files),'published_compressed_bytes':total,'counts':merged['counts'],
        'old_class_shards_rewritten':False,'manifest_activated_last':True,'formal_adoption':False,
        'checked_at':datetime.now(timezone.utc).isoformat()}
    (OUTPUT/'activation-readback.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
