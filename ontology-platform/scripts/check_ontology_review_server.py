"""Focused safety and RDF-response checks; no database is started."""
import unittest
import json
from pathlib import Path
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import urlopen, Request
from http.server import ThreadingHTTPServer
from serve_ontology_review import GraphReader, checked_iri, checked_endpoint, make_handler


class ReaderTests(unittest.TestCase):
    def test_iri_cannot_escape_a_sparql_term(self):
        for value in ('urn:x> } UNION { ?s ?p ?o','urn:x\n','javascript:alert(1)',''):
            with self.assertRaises(ValueError):checked_iri(value)
        self.assertEqual(checked_iri('https://w3id.org/lzo/ontology/Pond'),'https://w3id.org/lzo/ontology/Pond')

    def test_only_explicit_loopback_fuseki_endpoint(self):
        for url in ('https://example.com/fish_l1','http://127.0.0.1:23049/fish_l1?x=1',
                    'http://name:password@127.0.0.1:23049/fish_l1','file:///tmp/x'):
            with self.assertRaises(ValueError):checked_endpoint(url)
        self.assertEqual(checked_endpoint('http://127.0.0.1:23049/fish_l1'),'http://127.0.0.1:23049/fish_l1')

    def test_resource_is_read_from_only_declared_named_graphs(self):
        reader=GraphReader('http://127.0.0.1:23049/fish_l1',['urn:lzo:fish-review:sample:v1:fixture'])
        queries=[]
        def query(value):
            queries.append(value)
            if '?predicate ?object' in value:
                return [{'predicate':{'type':'uri','value':'urn:depth'},'object':{
                    'type':'literal','value':'1.80','datatype':'http://www.w3.org/2001/XMLSchema#decimal'}}]
            return [{'subject':{'type':'uri','value':'urn:other'},'predicate':{'type':'uri','value':'urn:related'},
                'label':{'type':'literal','value':'关联对象','xml:lang':'zh'}}]
        reader.query=query
        result=reader.resource('urn:example:pond')
        self.assertEqual(result['outgoing'][0]['object']['value'],'1.80')
        self.assertEqual(result['incoming'][0]['label'],'关联对象')
        for value in queries:
            self.assertIn('urn:lzo:fish-review:sample:v1:fixture',value)
            self.assertNotIn('UPDATE',value)
            self.assertNotIn('INSERT',value)

    def test_resource_has_independent_stable_pages_for_large_link_groups(self):
        reader=GraphReader('http://127.0.0.1:23049/fish_l1',['urn:graph:first'])
        queries=[]
        def query(value):
            queries.append(value)
            if '?predicate ?object' in value:
                return [{'predicate':{'value':'urn:p'},'object':{'type':'uri','value':'urn:o:'+str(i)}} for i in range(3)]
            return []
        reader.query=query
        result=reader.resource('urn:pond',2,4,7)
        self.assertEqual(result['next_outgoing_offset'],6)
        self.assertIsNone(result['next_incoming_offset'])
        self.assertEqual(len(result['outgoing']),2)
        self.assertIn('COUNT(DISTINCT ?candidate)',queries[0])
        self.assertIn('ORDER BY ?fanout ?predicate ?object LIMIT 3 OFFSET 4',queries[0])
        self.assertIn('OFFSET 7',queries[1])

    def test_missing_graph_is_not_reported_as_live_data(self):
        with self.assertRaises(ValueError):GraphReader('http://127.0.0.1:23049/fish_l1',[])

    def test_navigation_queries_the_chosen_class_and_subclasses(self):
        reader=GraphReader('http://127.0.0.1:23049/fish_l1',['urn:graph:first','urn:graph:second'])
        queries=[]
        def query(value):
            queries.append(value)
            if '?instance ?label' in value:return [{'instance':{'type':'uri','value':'urn:pond:one'}}]
            return [{'class':{'type':'uri','value':'urn:child'},'label':{'value':'子本体'}}]
        reader.query=query
        self.assertEqual(reader.children('urn:root')['items'][0]['label'],'子本体')
        self.assertEqual(reader.instances('urn:child')['items'][0]['iri'],'urn:pond:one')
        self.assertIn('rdf:type/rdfs:subClassOf* <urn:child>',queries[1])
        self.assertTrue(all('FROM <urn:graph:first> FROM <urn:graph:second>' in q for q in queries))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);(root/'index.html').write_text('<h1>RDF ontology</h1>')
        class Reader:
            def status(self):return {'mode':'fuseki','available':True,'sql_used':False}
            def resource(self,iri,limit,outgoing_offset,incoming_offset):return {'iri':checked_iri(iri),'outgoing':[],'incoming':[],'mode':'fuseki'}
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root,Reader()))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.addCleanup(self.shutdown)

    def shutdown(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

    def test_status_is_live_reader_and_no_global_instance_dump(self):
        with urlopen(self.base+'/api/ontology/status') as response:
            self.assertEqual(json.load(response),{'mode':'fuseki','available':True,'sql_used':False})
        with self.assertRaises(HTTPError) as caught:urlopen(self.base+'/api/ontology/instances')
        self.assertEqual(caught.exception.code,400)

    def test_post_is_not_sparql_update(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.base+'/api/ontology/resource',data=b'INSERT DATA {}',method='POST'))
        self.assertEqual(caught.exception.code,405)

    def test_private_files_and_traversal_are_not_served(self):
        for path in ('/.env','/%2e%2e/private','/api/ontology/unknown'):
            with self.assertRaises(HTTPError) as caught:urlopen(self.base+path)
            self.assertEqual(caught.exception.code,404)


if __name__=='__main__':unittest.main()
