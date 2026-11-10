"""Verified-model RDF equality and bounded public snapshot regressions."""
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from rdflib.namespace import RDF
from csv_batch_model import build_snapshot
from check_csv_batch_model import fixture,DEFINITIONS,RULES,PACKAGE
from fish_rdf_sample import project,triple_digest,PROV

NS='urn:lzo:csv-batch:v1:'+PACKAGE+':'
STATE='csv_batch_not_formally_adopted'


class DeliveryTests(unittest.TestCase):
    def model(self):
        self.assertIsNotNone(importlib.util.find_spec('csv_batch_delivery'),'Bounded CSV delivery is not implemented')
        import csv_batch_delivery
        return csv_batch_delivery

    def snapshot(self):return build_snapshot(fixture(),DEFINITIONS,RULES,PACKAGE)[0]

    def test_canonical_validation_view_is_exact_projection_term_subset(self):
        model=self.model();snapshot=self.snapshot()
        records=model.CanonicalRecords(snapshot,NS)
        actual={triple_digest(s,p,o) for s,p,o in records.triples()}
        expected={triple_digest(s,p,o) for s,p,o in project(snapshot,namespace=NS,state=STATE)
            if str(s).startswith(NS+'instance:') and (p==RDF.type or p==PROV.wasDerivedFrom
                or str(p).startswith((NS+'property:',NS+'relation:')))}
        self.assertEqual(actual,expected)

    def test_detail_keeps_decimal_lexical_precision_and_source_identity(self):
        model=self.model();snapshot=self.snapshot();index=model.Indices(snapshot)
        node=next(x for x in snapshot['nodes'] if x['table_name']=='events' and x['source_pk']=='E1')
        detail=model.detail(node,snapshot,index,NS,{}, {})
        value=next(x for x in detail['properties'] if x['field']=='quantity_kg')
        self.assertEqual(value['value'],'123456789012345678.123456789')
        self.assertEqual(detail['table'],'csv_events')
        self.assertEqual(detail['provenance']['sample_reason'],'full_csv_batch')
        self.assertNotIn('payload',detail['provenance'])
        self.assertTrue(detail['outgoing'])
        self.assertTrue(detail['unresolved_relations'])

    def test_publication_requires_complete_termset_proof(self):
        model=self.model();snapshot=self.snapshot()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):model.write_classes(snapshot,NS,{}, {},Path(directory),{})

    def test_high_degree_edges_are_paged_and_summaries_have_bounded_details(self):
        model=self.model();tables=fixture();tables['events']=[{'id':'E'+str(i),'pond_id':'001','quantity_kg':'1',
            'occurred_at':'2025-01-01T00:00:00+08:00','related_ids':''} for i in range(1001)]
        snapshot,_=build_snapshot(tables,DEFINITIONS,RULES,PACKAGE)
        proof={'status':'passed','full_terms_equal':True,'package_sha256':PACKAGE,'graph_iri':NS+'graph:'+'b'*64}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            report=model.write_classes(snapshot,NS,{}, {},root,proof)
            summary=json.loads(gzip.decompress((root/'classes/csv_ponds.json.gz').read_bytes()))['instances'][0]
            self.assertNotIn('properties',summary)
            full=json.loads(gzip.decompress((root/summary['detail_path']).read_bytes()))['instances'][0]
            self.assertEqual(full['incoming'],[])
            self.assertEqual(full['incoming_count'],1001)
            self.assertEqual(full['incoming_page_size'],4800)
            page=json.loads(gzip.decompress((root/full['incoming_pages'][0]).read_bytes()))
            self.assertEqual(len(page['edges']),1001)
            self.assertEqual(page['instance_iri'],full['iri'])
            self.assertEqual(page['direction'],'incoming')
            events=json.loads(gzip.decompress((root/'classes/csv_events.json.gz').read_bytes()))
            self.assertEqual(len(events['instances']),1001)
            self.assertEqual(len({x['detail_path'] for x in events['instances']}),3)
            self.assertEqual(report['instances'],len(snapshot['nodes']))


if __name__=='__main__':unittest.main()
