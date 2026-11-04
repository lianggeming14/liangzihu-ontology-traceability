"""Serve hierarchical ontology review and read-only live SPARQL on loopback.

Only the graph IRIs recorded in the verified RDF manifest are queried. This
process does not connect to SQL, start workers, or expose SPARQL Update.
"""
from __future__ import annotations
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY=ROOT/'docs/fish/ontology-review'


def checked_iri(value):
    if (not isinstance(value,str) or len(value)>2048 or not value.startswith(('urn:','http://','https://'))
            or re.search(r'[\x00-\x20<>"{}|^`\\]',value)):
        raise ValueError('Invalid RDF IRI')
    return value


def checked_endpoint(value):
    url=urlsplit(value)
    if (url.scheme!='http' or url.hostname!='127.0.0.1' or url.port is None
            or url.username or url.password or url.query or url.fragment
            or not re.fullmatch(r'/[a-zA-Z0-9_-]+',url.path)):
        raise ValueError('Explicit loopback Fuseki dataset URL required')
    return value.rstrip('/')


class GraphReader:
    def __init__(self,endpoint,graphs):
        self.endpoint=checked_endpoint(endpoint)
        self.graphs=tuple(dict.fromkeys(checked_iri(x) for x in graphs))
        if not self.graphs:raise ValueError('Verified RDF manifest has no named graphs')

    def query(self,value):
        import httpx
        with httpx.Client(timeout=25,trust_env=False) as client:
            response=client.post(self.endpoint+'/query',data={'query':value},
                headers={'Accept':'application/sparql-results+json'})
            response.raise_for_status()
            return response.json()['results']['bindings']

    def values(self):return 'VALUES ?graph { '+' '.join('<'+x+'>' for x in self.graphs)+' }'

    def dataset(self):return ' '.join('FROM <'+x+'>' for x in self.graphs)

    def children(self,parent):
        parent=checked_iri(parent)
        query=('PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> '
            'PREFIX owl: <http://www.w3.org/2002/07/owl#> '
            'SELECT DISTINCT ?class ?label '+self.dataset()+' WHERE { '
            '?class a owl:Class ; rdfs:subClassOf <'+parent+'> . OPTIONAL { ?class rdfs:label ?label } '
            '} ORDER BY ?class ?label')
        return {'parent':parent,'mode':'fuseki','items':[{'iri':row['class']['value'],
            'label':row.get('label',{}).get('value',row['class']['value'])} for row in self.query(query)]}

    def instances(self,concept,offset=0,limit=30):
        concept=checked_iri(concept);offset=max(0,min(int(offset),1000000));limit=max(1,min(int(limit),100))
        query=('PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> '
            'PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> '
            'SELECT DISTINCT ?instance ?label '+self.dataset()+' WHERE { '
            '?instance rdf:type/rdfs:subClassOf* <'+concept+'> . OPTIONAL { ?instance rdfs:label ?label } '
            '} ORDER BY ?instance ?label LIMIT '+str(limit+1)+' OFFSET '+str(offset))
        rows=self.query(query)
        return {'class_iri':concept,'mode':'fuseki','offset':offset,'limit':limit,
            'next_offset':offset+limit if len(rows)>limit else None,
            'items':[{'iri':row['instance']['value'],'label':row.get('label',{}).get('value',row['instance']['value'])}
                for row in rows[:limit]]}

    def status(self):
        rows=self.query('SELECT (COUNT(*) AS ?count) WHERE { '+self.values()+' GRAPH ?graph { ?s ?p ?o } }')
        counts=self.query('SELECT ?graph (COUNT(*) AS ?count) WHERE { '+self.values()+
            ' GRAPH ?graph { ?s ?p ?o } } GROUP BY ?graph')
        present={row['graph']['value']:int(row['count']['value']) for row in counts}
        return {'mode':'fuseki','available':all(present.get(g,0)>0 for g in self.graphs),
            'graph_iris':self.graphs,'triple_count':int(rows[0]['count']['value']),
            'graph_counts':present,'sql_used':False,'read_only':True}

    def resource(self,identifier,limit=500,outgoing_offset=0,incoming_offset=0):
        identifier=checked_iri(identifier);limit=max(1,min(int(limit),500))
        outgoing_offset=max(0,min(int(outgoing_offset),1000000))
        incoming_offset=max(0,min(int(incoming_offset),1000000))
        prefixes='PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> '
        # Return small property groups before large inverse/demo collections.
        # Both directions remain fully pageable; no links are silently dropped.
        fanout='{ SELECT ?predicate (COUNT(DISTINCT ?candidate) AS ?fanout) WHERE { '+self.values()+\
            ' GRAPH ?graph { <'+identifier+'> ?predicate ?candidate } } GROUP BY ?predicate } '
        outgoing=self.query(prefixes+'SELECT DISTINCT ?predicate ?object ?label ?fanout WHERE { '+fanout+self.values()+
            ' GRAPH ?graph { <'+identifier+'> ?predicate ?object . OPTIONAL { ?predicate rdfs:label ?label } } } '
            'ORDER BY ?fanout ?predicate ?object LIMIT '+str(limit+1)+' OFFSET '+str(outgoing_offset))
        incoming=self.query(prefixes+'SELECT DISTINCT ?subject ?predicate ?label WHERE { '+self.values()+
            ' GRAPH ?graph { ?subject ?predicate <'+identifier+'> . OPTIONAL { ?subject rdfs:label ?label } } } '
            'ORDER BY ?predicate ?subject LIMIT '+str(limit+1)+' OFFSET '+str(incoming_offset))
        return {'iri':identifier,'mode':'fuseki','sql_used':False,'graph_iris':self.graphs,
            'outgoing':[{'predicate':r['predicate']['value'],'object':r['object'],
                'label':r.get('label',{}).get('value')} for r in outgoing[:limit]],
            'incoming':[{'subject':r['subject']['value'],'predicate':r['predicate']['value'],
                'label':r.get('label',{}).get('value')} for r in incoming[:limit]],
            'limit':limit,'outgoing_offset':outgoing_offset,'incoming_offset':incoming_offset,
            'next_outgoing_offset':outgoing_offset+limit if len(outgoing)>limit else None,
            'next_incoming_offset':incoming_offset+limit if len(incoming)>limit else None,
            'truncated':len(outgoing)>limit or len(incoming)>limit}


def manifest_graphs(directory):
    value=json.loads((directory/'data/manifest.json').read_text(encoding='utf-8'))
    if value.get('fuseki_readback') is not True:
        raise ValueError('RDF graph has not passed recorded Fuseki readback')
    graphs=value.get('rdf_graphs')
    if not isinstance(graphs,list):raise ValueError('RDF manifest must declare rdf_graphs')
    return graphs


def make_handler(directory,reader):
    directory=Path(directory).resolve()
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(directory),**kwargs)

        def end_headers(self):
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            super().end_headers()

        def send_json(self,value,status=200):
            data=json.dumps(value,ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

        def do_GET(self):
            request=urlsplit(self.path)
            if request.path.startswith('/api/ontology/'):
                try:
                    # Each request uses one complete verified manifest revision.
                    # A new immutable graph can become visible after its RDF
                    # readback without restarting this read-only server.
                    active=GraphReader(reader.endpoint,manifest_graphs(directory)) if isinstance(reader,GraphReader) else reader
                    if request.path=='/api/ontology/status':return self.send_json(active.status())
                    if getattr(reader,'snapshot_only',False) and request.path in {
                            '/api/ontology/children','/api/ontology/instances','/api/ontology/resource'}:
                        return self.send_json({'mode':'rdf-snapshot','available':False,
                            'error':'This session reads the verified RDF snapshot; live Fuseki is not enabled'},503)
                    if request.path=='/api/ontology/children':
                        params=parse_qs(request.query)
                        if set(params)!={'parent'} or len(params['parent'])!=1:
                            return self.send_json({'error':'One parent ontology IRI is required'},400)
                        return self.send_json(active.children(params['parent'][0]))
                    if request.path=='/api/ontology/instances':
                        params=parse_qs(request.query)
                        if set(params)-{'class','offset','limit'} or len(params.get('class',[]))!=1:
                            return self.send_json({'error':'Choose one ontology class before reading instances'},400)
                        return self.send_json(active.instances(params['class'][0],params.get('offset',['0'])[0],params.get('limit',['30'])[0]))
                    if request.path=='/api/ontology/resource':
                        params=parse_qs(request.query)
                        if set(params)-{'iri','limit','outgoing_offset','incoming_offset'} or len(params.get('iri',[]))!=1:
                            return self.send_json({'error':'One resource IRI is required'},400)
                        return self.send_json(active.resource(params['iri'][0],params.get('limit',['500'])[0],
                            params.get('outgoing_offset',['0'])[0],params.get('incoming_offset',['0'])[0]))
                    return self.send_json({'error':'Unknown read-only ontology route'},404)
                except ValueError:return self.send_json({'error':'Invalid ontology request'},400)
                except Exception as error:
                    return self.send_json({'mode':'fuseki','available':False,
                        'error':'Live RDF read failed','exception_type':type(error).__name__},503)
            relative=unquote(request.path).lstrip('/')
            path=(directory/relative).resolve()
            if not path.is_relative_to(directory) or any(p.startswith('.') for p in Path(relative).parts):
                return self.send_json({'error':'Not found'},404)
            if path.is_dir() and not (path/'index.html').is_file():return self.send_json({'error':'Not found'},404)
            return super().do_GET()

        def do_POST(self):return self.send_json({'error':'Only read operations are exposed'},405)
        do_PUT=do_POST
        do_DELETE=do_POST

        def log_message(self,format,*args):
            # Avoid recording raw resource/query strings or external credentials.
            pass
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=DEFAULT_DIRECTORY)
    parser.add_argument('--fuseki-url',default='http://127.0.0.1:23049/fish_l1')
    parser.add_argument('--port',type=int,default=8792)
    parser.add_argument('--offline',action='store_true',help='Browse the verified RDF-derived snapshots without connecting to Fuseki')
    args=parser.parse_args()
    if args.port!=0 and not 1024<=args.port<=65535:parser.error('Use a nonprivileged local port, or 0 for an OS-assigned local port')
    graphs=manifest_graphs(args.directory)
    if args.offline:
        class SnapshotReader:
            snapshot_only=True
            def status(self):return {'mode':'rdf-snapshot','available':False,'graph_iris':graphs,
                'snapshot_verified':True,'sql_used':False,'read_only':True}
        reader=SnapshotReader();status=reader.status()
    else:
        reader=GraphReader(args.fuseki_url,graphs);status=reader.status()
        if not status['available']:raise SystemExit('Verified named graph is not present in this Fuseki dataset')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(args.directory,reader))
    print(json.dumps({'url':f'http://127.0.0.1:{server.server_port}/',**status},ensure_ascii=False),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
