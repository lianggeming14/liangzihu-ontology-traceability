import unittest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD, OWL
from fish_drawing_rdf import NS, project_drawing, DrawingNavigation


def fixture():
    return {'content_sha256':'a'*64,'source_package_sha256':'b'*64,'nodes':[
        {'id':'field','class_iri':'https://w3id.org/lzo/ontology/Field','label':'田块图纸档案',
         'data_nature':'imported_unverified','properties':[],'source_drawing_ids':['pdf-01']},
        {'id':'measure','class_iri':'urn:lzo:drawing-ontology:Measurement','label':'周长',
         'data_nature':'imported_unverified','source_drawing_ids':['pdf-01'],'properties':[
             {'predicate_iri':'urn:lzo:drawing-ontology:numericValue','term':{'kind':'literal','value':'3.00','datatype_iri':str(XSD.decimal)},'evidence_ids':['ev-1']},
             {'predicate_iri':'urn:lzo:drawing-ontology:unit','term':{'kind':'literal','value':'pt','datatype_iri':str(XSD.string)},'evidence_ids':['ev-1']}]}],
        'edges':[{'subject_id':'field','predicate_iri':'urn:lzo:drawing-ontology:hasMeasurement',
                  'object_id':'measure','evidence_ids':['ev-1'],'derivation':'paper geometry'}]}


class DrawingChecks(unittest.TestCase):
    def build(self):
        maps={'objects':[{'source_resource_id':'field','object_iri':'urn:map:field',
            'class_iri':'urn:map:class:Field','label':'实图田块'}]}
        return Graph().parse(data=''.join(s.n3()+' '+p.n3()+' '+o.n3()+'.\n' for s,p,o in project_drawing(fixture(),maps)),format='nt')

    def test_measurement_is_typed_and_inverse_link_exists(self):
        g=self.build();s=URIRef(NS+'instance:measure')
        self.assertIn((s,URIRef('urn:lzo:drawing-ontology:numericValue'),Literal('3.0',datatype=XSD.decimal,normalize=False)),g)
        self.assertIn((URIRef(NS+'instance:field'),URIRef('urn:lzo:drawing-ontology:hasMeasurement'),s),g)
        self.assertTrue(list(g.triples((s,URIRef('urn:lzo:drawing-ontology:hasMeasurement:inverse'),None))))

    def test_exact_source_uuid_creates_evidence_bridge_not_sameas(self):
        g=self.build()
        self.assertIn((URIRef('urn:map:field'),URIRef(NS+'hasDrawingEvidence'),URIRef(NS+'instance:field')),g)
        self.assertFalse(list(g.triples((None,OWL.sameAs,None))))

    def test_navigation_comes_from_returned_rdf(self):
        nav=DrawingNavigation()
        for triple in self.build():nav.add(*triple)
        manifest,classes=nav.finish()
        self.assertEqual(manifest['counts']['instances'],2)
        node=next(n for table in classes.values() for n in table['instances'] if n['id']=='measure')
        self.assertEqual(node['properties'][0]['nature'],'imported_unverified')
        self.assertTrue(node['incoming'])

    def test_dangling_original_edge_is_rejected(self):
        value=fixture();value['edges'][0]['object_id']='missing'
        with self.assertRaises(ValueError):list(project_drawing(value))


if __name__=='__main__':unittest.main()
