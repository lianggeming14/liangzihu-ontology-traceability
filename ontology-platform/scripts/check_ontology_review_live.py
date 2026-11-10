"""Exercise actual hierarchy/instance/map/evidence reads through live SPARQL."""
import argparse
from datetime import datetime,timezone
import json
import gzip
from pathlib import Path
from urllib.parse import urlsplit
import httpx

ROOT=Path(__file__).resolve().parents[1]
NS='urn:lzo:fish-review:sample:v1:'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8792')
    parser.add_argument('--report',type=Path,default=ROOT/'docs/fish/ontology-review/live-api-readback.json')
    args=parser.parse_args();url=urlsplit(args.base_url)
    if url.scheme!='http' or url.hostname!='127.0.0.1' or url.port is None or url.username or url.password or url.query:
        raise ValueError('Explicit loopback review server required')
    if not __debug__:raise ValueError('Do not use Python -O for validation')
    manifest=json.loads((ROOT/'docs/fish/ontology-review/data/manifest.json').read_text(encoding='utf-8'))
    with httpx.Client(base_url=args.base_url,timeout=30,trust_env=False) as client:
        def get(path,**params):
            result=client.get('/api/ontology/'+path,params=params);result.raise_for_status();return result.json()
        status=get('status');assert status['available'] and status['mode']=='fuseki' and not status['sql_used']
        assert set(status['graph_iris'])==set(manifest['rdf_graphs'])
        assert status['triple_count']==manifest['counts']['triples']
        children=get('children',parent=manifest['root_iri']);assert children['items']
        first=get('instances',**{'class':NS+'class:ponds','limit':2})
        assert len(first['items'])==2 and first['next_offset']==2
        second=get('instances',**{'class':NS+'class:ponds','limit':2,'offset':2})
        assert not {x['iri'] for x in first['items']} & {x['iri'] for x in second['items']}
        pond=get('resource',iri=first['items'][0]['iri'])
        assert any(x['predicate']==NS+'property:ponds:mean_depth_m' and x['object']['value']=='1.8' for x in pond['outgoing'])
        assert any(x['predicate'].endswith('relation:ponds:farm_id:farms') for x in pond['outgoing'])
        maps=json.loads((ROOT/'datasets/farm-map/map-objects.json').read_text(encoding='utf-8'))
        target=next(x for x in maps['objects'] if x['kind']=='pond' and x['asset_id']!='full')
        real=get('resource',iri=target['object_iri'])
        bridge=next(x for x in real['outgoing'] if x['predicate']=='urn:lzo:fish-review:drawing:v1:hasDrawingEvidence')
        assert any(x['predicate']=='urn:lzo:fish-review:demo:v1:demoProfileFrom' for x in real['outgoing'])
        evidence=get('resource',iri=bridge['object']['value'])
        measurement=next(x for x in evidence['outgoing'] if x['predicate']=='urn:lzo:drawing-ontology:hasMeasurement')
        measure=get('resource',iri=measurement['object']['value'])
        assert any(x['predicate']=='urn:lzo:drawing-ontology:numericValue' for x in measure['outgoing'])
        assert any(x['predicate']=='urn:lzo:drawing-ontology:hasMeasurement:inverse' for x in measure['outgoing'])
        assert client.post('/api/ontology/resource',content='INSERT DATA {}').status_code==405
        csv_checks={};csv_examples={}
        if manifest.get('csv_batches'):
            concept=next(item for item in manifest['concepts'] if item.get('table')=='csv_ponds')
            csv_children=get('children',parent='https://w3id.org/lzo/ontology/Pond')
            assert concept['iri'] in {item['iri'] for item in csv_children['items']}
            csv_first=get('instances',**{'class':concept['iri'],'limit':2})
            assert len(csv_first['items'])==2 and csv_first['next_offset']==2
            identifier=csv_first['items'][0]['iri']
            summary=json.loads(gzip.decompress((ROOT/'docs/fish/ontology-review/data'/concept['instances_path']).read_bytes()))
            row=next(item for item in summary['instances'] if item['iri']==identifier)
            detail=json.loads(gzip.decompress((ROOT/'docs/fish/ontology-review/data'/row['detail_path']).read_bytes()))
            row=next(item for item in detail['instances'] if item['iri']==identifier)
            depth=next(prop for prop in row['properties'] if prop['field']=='mean_depth_m' and prop['value'] is not None)
            csv_resource=get('resource',iri=identifier)
            assert any(item['predicate']==depth['iri'] and item['object'].get('datatype')==depth['datatype']
                and item['object']['value']==depth['value'] for item in csv_resource['outgoing'])
            farm=next(item for item in csv_resource['outgoing'] if item['predicate'].endswith('relation:ponds:farm_id:farms'))
            assert farm['object']['value'].startswith(concept['iri'].rsplit('class:',1)[0]+'instance:')
            next_offset=csv_resource['next_incoming_offset'];assert next_offset is not None
            more=get('resource',iri=identifier,incoming_offset=next_offset)
            one={(item['subject'],item['predicate']) for item in csv_resource['incoming']}
            two={(item['subject'],item['predicate']) for item in more['incoming']}
            assert two and not one&two
            csv_checks={'csv_leaf_under_shared_pond_ontology':'passed','csv_class_scoped_pagination':'passed',
                'csv_depth_matches_exact_verified_snapshot':'passed','csv_farm_target_stays_in_its_batch':'passed',
                'csv_high_degree_incoming_pagination':'passed'}
            csv_examples={'csv_pond':identifier,'csv_farm':farm['object']['value']}
    report={'contract':'ontology-live-api-readback/1','status':'passed','checked_at':datetime.now(timezone.utc).isoformat(),
        'mode':'actual_fuseki_sparql','database_mutations':0,'sql_connections':0,'graphs':status['graph_iris'],
        'triple_count':status['triple_count'],'checks':{'root_children':len(children['items']),
            'class_scoped_pagination':'passed','typed_source_pond_depth':'passed','source_pond_farm_relation':'passed',
            'actual_map_to_drawing_evidence':'passed','drawing_to_typed_measurement':'passed',
            'measurement_inverse':'passed','demo_profile_separated':'passed','post_write_rejected':'passed',**csv_checks},
        'examples':{'source_pond':first['items'][0]['iri'],'map_pond':target['object_iri'],
            'drawing_evidence':bridge['object']['value'],'measurement':measurement['object']['value'],**csv_examples}}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','triple_count':report['triple_count'],'checks':report['checks']}))


if __name__=='__main__':main()
