"""Exercise actual hierarchy/instance/map/evidence reads through live SPARQL."""
import argparse
from datetime import datetime,timezone
import json
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
        assert set(status['graph_iris'])==set(manifest['rdf_graphs']) and len(status['graph_iris'])==4
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
    report={'contract':'ontology-live-api-readback/1','status':'passed','checked_at':datetime.now(timezone.utc).isoformat(),
        'mode':'actual_fuseki_sparql','database_mutations':0,'sql_connections':0,'graphs':status['graph_iris'],
        'triple_count':status['triple_count'],'checks':{'root_children':len(children['items']),
            'class_scoped_pagination':'passed','typed_source_pond_depth':'passed','source_pond_farm_relation':'passed',
            'actual_map_to_drawing_evidence':'passed','drawing_to_typed_measurement':'passed',
            'measurement_inverse':'passed','demo_profile_separated':'passed','post_write_rejected':'passed'},
        'examples':{'source_pond':first['items'][0]['iri'],'map_pond':target['object_iri'],
            'drawing_evidence':bridge['object']['value'],'measurement':measurement['object']['value']}}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','triple_count':report['triple_count'],'checks':report['checks']}))


if __name__=='__main__':main()
