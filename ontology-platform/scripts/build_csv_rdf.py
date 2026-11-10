"""Build and exactly verify the pinned full CSV batch in a new Jena graph.

Only --apply exposes writes, and only to a content-addressed graph of this
package in the isolated local dataset. Public data is staged, not activated.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import gc
import hashlib
from itertools import chain
import json
from pathlib import Path
import re
import time

import httpx
import rdflib
from rdflib import Graph,Literal,Namespace,URIRef
from rdflib.namespace import RDF,RDFS,OWL,XSD
from rdflib.plugins.parsers.ntriples import W3CNTriplesParser
from rdflib.plugins.serializers.nt import _quoteLiteral

from prepare_csv_batch import prepare
from csv_batch_model import read_tables,build_snapshot
from csv_batch_delivery import CanonicalRecords,write_classes,STATE
from fish_rdf_sample import C,PROV,LABELS,TABLE_DOMAINS,Navigation,project,triple_digest,uri_factory
from fish_rdf_validation import shapes,validate_canonical

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524'
NS='urn:lzo:csv-batch:v1:'+PACKAGE+':'
V=Namespace(NS)
ENDPOINT='http://127.0.0.1:23049/fish_l1'
RUNTIME=ROOT/'.runtime/csv-batch-20261109'
SOURCE=ROOT/'.runtime/source-imports/csv-2026-11-09/cb9353499b6e'
OUTPUT=ROOT/'docs/csv-batch'
CSV_LABELS={key:'CSV · '+value for key,value in {**LABELS,'grade_definitions':'规格分级定义',
    'harvest_grade_individuals':'起捕个体分级','source_registry':'批次来源注册'}.items()}
CSV_DOMAINS={**TABLE_DOMAINS,'grade_definitions':'ReferenceRecord','harvest_grade_individuals':'Observation',
    'source_registry':'Document'}


def emit(value):print(json.dumps(value,ensure_ascii=True),flush=True)
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


def check_target(endpoint,graph):
    if endpoint!=ENDPOINT or not re.fullmatch(re.escape(NS)+r'graph:[0-9a-f]{64}',graph):
        raise ValueError('Only the pinned CSV package graph in the reviewed local dataset is writable')


def nt_chunks(path,max_lines=250000):
    with Path(path).open('rb') as stream:
        lines=[]
        for line in stream:
            lines.append(line)
            if len(lines)>=max_lines:
                yield b''.join(lines);lines=[]
        if lines:yield b''.join(lines)


def read_inventory(path,expected_count,expected_sha):
    result=set();hasher=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while digest:=stream.read(32):
            if len(digest)!=32:raise ValueError('Truncated digest inventory')
            result.add(digest);hasher.update(digest)
    if len(result)!=expected_count or hasher.hexdigest()!=expected_sha:
        raise ValueError('Cached RDF digest inventory changed')
    return result


def select(client,query):
    response=client.post(ENDPOINT+'/query',data={'query':query,'timeout':'600000'},
        headers={'Accept':'application/sparql-results+json'})
    response.raise_for_status();return response.json()


def inventory(client):
    result=select(client,'SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g')
    return {item['g']['value']:int(item['n']['value']) for item in result['results']['bindings']}


def source_snapshot():
    manifest=prepare(SOURCE/'source.zip',SOURCE/'extracted')
    if manifest['archive_sha256']!=PACKAGE or manifest['csv_status']!='passed':raise ValueError('Wrong or invalid source archive')
    published=json.loads((OUTPUT/'source-manifest.json').read_text(encoding='utf-8'))
    if {(x['path'],x['sha256'],x['bytes']) for x in manifest['members']}!={(x['path'],x['sha256'],x['bytes']) for x in published['members']}:
        raise ValueError('Published source file inventory differs')
    tables,metadata=read_tables(SOURCE/'extracted',manifest)
    definitions=json.loads((ROOT/'datasets/fish/source-schema.json').read_text(encoding='utf-8'))
    rules=json.loads((OUTPUT/'relation-map.json').read_text(encoding='utf-8'))['relations']
    snapshot,report=build_snapshot(tables,definitions,rules,PACKAGE,metadata=metadata)
    if (report['source_tables'],report['raw_rows'],report['instances'],report['relations'])!=(66,153862,153862,810934):
        raise ValueError('CSV batch is incomplete')
    if any(report[k] for k in ('invalid_typed_cells','conflicting_rows','quarantined_rows','duplicate_rows')):
        raise ValueError('CSV typed or identity issues require review')
    del tables;gc.collect()
    return snapshot,report,manifest,metadata,rules


def source_provenance(snapshot,manifest,metadata):
    u=uri_factory(NS);dataset=URIRef(NS+'dataset:'+PACKAGE)
    yield dataset,PROV.wasDerivedFrom,URIRef('https://github.com/lianggeming14/upload-files/blob/'+manifest['source_commit']+'/csv.zip')
    for field,dtype in [('sourceMember',XSD.string),('sourceMemberSHA256',XSD.string),('csvLineEnd',XSD.integer),('sourceOriginKind',XSD.string)]:
        yield V[field],RDF.type,OWL.DatatypeProperty
        yield V[field],RDFS.range,dtype
    registry={node['properties'].get('table',node['source_pk']):node for node in snapshot['nodes'] if node['table_name']=='source_registry'}
    for table,member in metadata.items():
        file=u('file',table)
        yield file,RDF.type,PROV.Entity
        yield file,PROV.wasDerivedFrom,dataset
        yield file,V.sourceMember,Literal(member['path'])
        yield file,V.sourceMemberSHA256,Literal(member['sha256'])
        if table in registry:
            descriptor=u('instance',registry[table]['node_id'])
            yield u('class',table),PROV.wasDerivedFrom,descriptor
            yield file,PROV.wasDerivedFrom,descriptor
    for row in snapshot['raw']:
        table=row['table_name'];member=metadata[table];subject=u('source',table,row['row_number'])
        yield subject,PROV.wasDerivedFrom,u('file',table)
        yield subject,V.sourceMember,Literal(member['path'])
        yield subject,V.sourceMemberSHA256,Literal(member['sha256'])
        yield subject,V.csvLineEnd,Literal(member['line_ends'][row['row_number']-1])
        if table in registry:yield subject,V.sourceOriginKind,Literal(registry[table]['properties']['origin_kind'])


def fingerprint(snapshot,manifest,rules):
    names=['build_csv_rdf.py','csv_batch_model.py','csv_batch_delivery.py','fish_rdf_sample.py','fish_rdf_validation.py']
    values={'package':PACKAGE,'files':[(x['path'],x['sha256']) for x in manifest['members']],
        'schema':snapshot['schema'],'rules':rules,'code':{name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in names}}
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def generate(snapshot,manifest,metadata,rules):
    RUNTIME.mkdir(parents=True,exist_ok=True)
    path=RUNTIME/'csv.nt';cache=RUNTIME/'generation.json';digest_path=RUNTIME/'triple-digests.bin'
    expected_fingerprint=fingerprint(snapshot,manifest,rules)
    if cache.exists() and path.exists() and digest_path.exists():
        prior=json.loads(cache.read_text(encoding='utf-8'))
        if prior.get('fingerprint')==expected_fingerprint:
            if hashlib.file_digest(path.open('rb'),'sha256').hexdigest()!=prior['nt_sha256']:raise ValueError('Cached RDF file changed')
            expected=read_inventory(digest_path,prior['triple_count'],prior['termset_sha256'])
            emit({'stage':'verified_generation_cache','triples':len(expected),'bytes':path.stat().st_size})
            return path,expected,Graph().parse(RUNTIME/'vocabulary.ttl',format='turtle'),prior
    expected=set();vocabulary=Graph();vocabulary_subjects=set();started=time.monotonic()
    with path.open('w',encoding='utf-8',newline='\n',buffering=1024*1024) as stream:
        for s,p,o in chain(project(snapshot,namespace=NS,state=STATE,labels=CSV_LABELS,table_domains=CSV_DOMAINS),
                source_provenance(snapshot,manifest,metadata)):
            digest=triple_digest(s,p,o)
            if digest in expected:continue
            expected.add(digest)
            stream.write(s.n3()+' '+p.n3()+' '+(_quoteLiteral(o) if isinstance(o,Literal) else o.n3())+' .\n')
            if p==RDF.type and o in (OWL.Class,OWL.ObjectProperty,OWL.DatatypeProperty,OWL.Ontology):vocabulary_subjects.add(s)
            if s in vocabulary_subjects or str(s).startswith(str(C)):vocabulary.add((s,p,o))
            if len(expected)%500000==0:emit({'stage':'rdf_generation','triples':len(expected),'seconds':round(time.monotonic()-started,1)})
    hasher=hashlib.sha256()
    with digest_path.open('wb',buffering=1024*1024) as stream:
        for digest in sorted(expected):hasher.update(digest);stream.write(digest)
    vocabulary.serialize(destination=str(RUNTIME/'vocabulary.ttl'),format='turtle')
    info={'fingerprint':expected_fingerprint,'triple_count':len(expected),'termset_sha256':hasher.hexdigest(),
        'nt_sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),'nt_bytes':path.stat().st_size}
    save(cache,info);emit({'stage':'rdf_generated',**info})
    return path,expected,vocabulary,info


class TermSink:
    def __init__(self,remaining):self.remaining=remaining;self.count=0
    def triple(self,s,p,o):
        digest=triple_digest(s,p,o)
        if digest not in self.remaining:raise ValueError('Unexpected, changed or duplicated RDF term from Jena')
        self.remaining.remove(digest);self.count+=1
        if self.count%500000==0:emit({'stage':'actual_jena_term_readback','triples':self.count})


def load_graph(path,expected,info,*,apply):
    graph=NS+'graph:'+info['termset_sha256'];check_target(ENDPOINT,graph)
    marker=RUNTIME/'graph-job.json'
    with httpx.Client(timeout=httpx.Timeout(600,connect=10),trust_env=False) as client:
        before=inventory(client);existing=before.get(graph,0)
        if existing!=info['triple_count']:
            if not apply:raise ValueError('Full CSV graph is not present; verification never writes')
            if existing:
                owned=json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
                if owned.get('graph_iri')!=graph or owned.get('nt_sha256')!=info['nt_sha256']:
                    raise ValueError('An unowned incomplete graph exists; refusing repair')
            save(marker,{'graph_iri':graph,'nt_sha256':info['nt_sha256'],'status':'loading'})
            sent=0
            for chunk in nt_chunks(path):
                check_target(ENDPOINT,graph)
                response=client.post(ENDPOINT+'/data',params={'graph':graph},content=chunk,
                    headers={'Content-Type':'application/n-triples','Content-Length':str(len(chunk))})
                response.raise_for_status();sent+=chunk.count(b'\n')
                emit({'stage':'csv_graph_upload','triples_sent':sent,'expected':info['triple_count']})
        returned=RUNTIME/'jena-readback.nt'
        with client.stream('GET',ENDPOINT+'/data',params={'graph':graph},
                headers={'Accept':'application/n-triples','Accept-Encoding':'identity'}) as response:
            response.raise_for_status()
            with returned.open('wb') as stream:
                for block in response.iter_bytes():stream.write(block)
        sink=TermSink(expected);prior=rdflib.NORMALIZE_LITERALS
        try:
            rdflib.NORMALIZE_LITERALS=False
            with returned.open(encoding='utf-8') as stream:W3CNTriplesParser(sink=sink).parse(stream)
        finally:rdflib.NORMALIZE_LITERALS=prior
        if expected or sink.count!=info['triple_count']:raise ValueError('Jena omitted expected CSV RDF terms')
        expected.clear();gc.collect()
        patterns={'instances':f'?s <{RDF.type}> ?c . ?c <{V.sourceTable}> ?table ; <{RDF.type}> <{OWL.Class}> .',
            'source_records':f'?s <{RDF.type}> <{V.SourceRecord}> .',
            'relations':f'?s <{RDF.type}> <{V.RelationRecord}> .',
            'resolved_relations':f'?s <{RDF.type}> <{V.RelationRecord}> ; <{V.resolution}> "resolved" .',
            'missing_inverse':f'?e <{RDF.type}> <{V.RelationRecord}> ; <{RDF.subject}> ?s ; <{RDF.predicate}> ?p ; <{RDF.object}> ?o . ?p <{OWL.inverseOf}> ?inv . FILTER NOT EXISTS {{ ?o ?inv ?s }}',
            'orphan_targets':f'?e <{RDF.type}> <{V.RelationRecord}> ; <{RDF.object}> ?target . FILTER NOT EXISTS {{ ?target <{V.sourcePK}> ?id }}'}
        checks={}
        for name,pattern in patterns.items():
            rows=select(client,'SELECT (COUNT(*) AS ?n) WHERE { GRAPH <'+graph+'> { '+pattern+' } }')['results']['bindings']
            checks[name]=int(rows[0]['n']['value']);emit({'stage':'csv_sparql_check','check':name,'value':checks[name]})
        if {k:checks[k] for k in ('instances','source_records','relations','resolved_relations')}!={
                'instances':153862,'source_records':153862,'relations':810934,'resolved_relations':810891}:
            raise ValueError('CSV graph structural counts differ')
        if checks['missing_inverse'] or checks['orphan_targets']:raise ValueError('CSV graph relationships are incomplete')
        after=inventory(client)
        if any(after.get(key)!=value for key,value in before.items() if key!=graph):raise ValueError('An older graph changed')
        report={'contract':'csv-rdf-readback/1','status':'passed','package_sha256':PACKAGE,'namespace':NS,
            'graph_iri':graph,'triple_count':sink.count,'termset_sha256':info['termset_sha256'],
            'nt_sha256':info['nt_sha256'],'full_terms_equal':True,'unexpected_or_missing_terms':0,'sparql':checks,
            'existing_complete_graph_reused':existing==info['triple_count'],'older_graph_counts_unchanged':True,
            'checked_at':datetime.now(timezone.utc).isoformat(),'formal_adoption':False,'raw_payload_public':False}
        save(marker,{**report,'nt_sha256':info['nt_sha256'],'status':'verified'})
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--apply',action='store_true');modes.add_argument('--verify',action='store_true')
    modes.add_argument('--generate-only',action='store_true')
    args=parser.parse_args();started=time.monotonic()
    snapshot,model_report,manifest,metadata,rules=source_snapshot()
    emit({'stage':'csv_source_model',**{k:v for k,v in model_report.items() if k!='tables'}})
    save(OUTPUT/'model-readback.json',model_report);save(OUTPUT/'field-dictionary.json',snapshot['schema'])
    path,expected,vocabulary,info=generate(snapshot,manifest,metadata,rules)
    if args.generate_only:return
    proof=load_graph(path,expected,info,apply=args.apply)
    shape_graph=shapes(snapshot['schema'],vocabulary,namespace=NS)
    navigation=Navigation(namespace=NS,state=STATE)
    navigation.records=CanonicalRecords(snapshot,NS)
    shacl=validate_canonical(navigation,shape_graph,namespace=NS,progress=emit)
    shacl['input_equality']='Exact canonical RDF view of the projection whose complete termset was verified equal to Jena readback'
    save(OUTPUT/'shacl-readback.json',shacl)
    if shacl['status']!='passed' or shacl['instances_validated']!=153862 or shacl['datatype_constraints']!=1397:
        raise ValueError('CSV SHACL was incomplete or failed')
    del navigation;gc.collect()
    staged=RUNTIME/'public'
    bounded=write_classes(snapshot,NS,metadata,CSV_LABELS,staged/'data',proof)
    vocabulary.serialize(destination=str(staged/'csv-vocabulary.ttl'),format='turtle')
    shape_graph.serialize(destination=str(staged/'csv-shapes.ttl'),format='turtle')
    for name in ('csv-vocabulary.ttl','csv-shapes.ttl'):
        target=staged/name;target.write_bytes(target.read_bytes().rstrip()+b'\n')
    save(OUTPUT/'navigation-files.json',bounded)
    proof.update(model=model_report,shacl={'status':'passed','instances_validated':153862,'datatype_constraints':1397,'violations':shacl['violations']},
        public_navigation={k:v for k,v in bounded.items() if k!='files'},activation='staged_not_active',
        seconds=round(time.monotonic()-started,2))
    save(OUTPUT/'rdf-readback.json',proof)
    save(staged/'model-schema.json',snapshot['schema'])
    emit({'stage':'csv_rdf_verified_staged','graph_iri':proof['graph_iri'],'triples':proof['triple_count'],
        'instances':model_report['instances'],'public_files':len(bounded['files']),'seconds':proof['seconds']})


if __name__=='__main__':
    try:main()
    except Exception as error:
        save(OUTPUT/'rdf-readback.json',{'contract':'csv-rdf-readback/1','status':'failed',
            'exception_type':type(error).__name__,'package_sha256':PACKAGE,'formal_adoption':False,'activation':'not_active'})
        emit({'status':'failed','exception_type':type(error).__name__});raise
