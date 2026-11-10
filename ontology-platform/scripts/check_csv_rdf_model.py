"""Namespace isolation and default-output regressions; synthetic, no services."""
import copy
import hashlib
import unittest

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD

from check_fish_rdf_sample import fixture
from fish_rdf_sample import NS, C, PROV, Navigation, project, triple_digest
from fish_rdf_validation import shapes, validate_canonical


CSV_NS = 'urn:lzo:csv-review:batch:sha256-example:'
CSV_STATE = 'csv_batch_not_formally_adopted'
LABELS = {'csv_farms': 'CSV farms', 'csv_ponds': 'CSV ponds', 'Pond': 'not a domain label'}
TABLE_DOMAINS = {'csv_farms': 'Farm', 'csv_ponds': 'Pond'}


def csv_fixture():
    snapshot = copy.deepcopy(fixture())
    snapshot.update({'source_schema': 'csv_batch_a4d78be79a83',
        'dataset_label': 'CSV DB-ready 全量批次 2026-11-09',
        'dataset_nature': 'synthetic revised rule simulation; weather reanalysis; reused asset catalog'})
    names = {'farms': 'csv_farms', 'ponds': 'csv_ponds'}
    snapshot['schema']['tables'] = {names[key]: value for key, value in snapshot['schema']['tables'].items()}
    for row in snapshot['nodes'] + snapshot['raw']:
        row['table_name'] = names[row['table_name']]
    for edge in snapshot['relations']:
        edge['target_table'] = names[edge['target_table']]
    columns = snapshot['schema']['tables']['csv_ponds']['columns']
    columns.update({'reading_count': {'type': 'integer'}, 'published': {'type': 'boolean'},
                    'observed_at': {'type': 'string', 'format': 'date-time'}})
    snapshot['nodes'][1]['properties'].update({'reading_count': 0, 'published': False,
        'observed_at': '2026-11-09T10:20:30Z'})
    for row in snapshot['raw']:
        if row['table_name'] == 'csv_ponds':
            row['payload'].update({'reading_count': '0', 'published': 'false',
                'observed_at': '2026-11-09T10:20:30Z'})
    return snapshot


class CSVModelChecks(unittest.TestCase):
    def build(self):
        graph = Graph()
        for triple in project(csv_fixture(), namespace=CSV_NS, state=CSV_STATE,
                              labels=LABELS, table_domains=TABLE_DOMAINS):
            graph.add(triple)
        return graph

    def navigation(self, graph):
        nav = Navigation(namespace=CSV_NS, state=CSV_STATE)
        for triple in graph: nav.add(*triple)
        return nav

    def test_default_fixture_termset_and_navigation_counts_are_unchanged(self):
        triples = set(project(fixture()))
        self.assertEqual(len(triples), 261)
        self.assertEqual(hashlib.sha256(b''.join(sorted(triple_digest(*t) for t in triples))).hexdigest(),
            'b47b622b8fcb99385b94c7aa3794569bad5822e83a42ed9e1b05a7b3e10d621a')
        nav = Navigation()
        for triple in triples: nav.add(*triple)
        manifest, _ = nav.finish()
        self.assertEqual(manifest['counts'], {'instances': 2, 'relations': 2,
            'resolved_relations': 1, 'classes': 22, 'source_classes': 2})
        self.assertEqual(manifest['namespace'], NS)

    def test_batch_metadata_and_source_leaf_classes_use_own_namespace(self):
        graph = self.build()
        self.assertFalse(any(isinstance(term, URIRef) and str(term).startswith(NS)
            for triple in graph for term in triple))
        self.assertIn((URIRef(CSV_NS + 'class:csv_ponds'), RDFS.subClassOf, C.Pond), graph)
        self.assertIn((URIRef(CSV_NS + 'class:csv_ponds'), RDFS.label, Literal('CSV ponds', lang='zh')), graph)
        self.assertNotIn((C.Pond, RDFS.label, Literal('not a domain label', lang='zh')), graph)
        self.assertIn((URIRef(CSV_NS + 'instance:p1'), URIRef(CSV_NS + 'adoptionStatus'), Literal(CSV_STATE)), graph)
        dataset = URIRef(CSV_NS + 'dataset:' + 'a' * 64)
        self.assertIn((dataset, RDF.type, OWL.Ontology), graph)
        self.assertIn((dataset, URIRef(CSV_NS + 'adoptionStatus'), Literal(CSV_STATE)), graph)
        self.assertIn((dataset, URIRef(CSV_NS + 'formalAdoption'), Literal(False)), graph)
        metadata = [
            (RDFS.label, Literal('CSV DB-ready 全量批次 2026-11-09', lang='zh')),
            (URIRef(CSV_NS + 'sourceSchema'), Literal('csv_batch_a4d78be79a83')),
            (URIRef(CSV_NS + 'dataNature'),
             Literal('synthetic revised rule simulation; weather reanalysis; reused asset catalog')),
        ]
        for predicate, value in metadata:
            with self.subTest(predicate=predicate):
                self.assertEqual(list(graph.objects(dataset, predicate)), [value])

    def test_two_interleaved_projections_have_no_source_edge_or_instance_collisions(self):
        default = project(fixture())
        batch = project(csv_fixture(), namespace=CSV_NS, state=CSV_STATE,
                        labels=LABELS, table_domains=TABLE_DOMAINS)
        old_graph, batch_graph = Graph(), Graph()
        while True:
            old, new = next(default, None), next(batch, None)
            if old is None and new is None: break
            if old is not None: old_graph.add(old)
            if new is not None: batch_graph.add(new)
        for kind, expected in [('source:', 3), ('edge:', 2), ('instance:', 2)]:
            old_ids = {str(s) for s in old_graph.subjects() if str(s).startswith(NS + kind)}
            new_ids = {str(s) for s in batch_graph.subjects() if str(s).startswith(CSV_NS + kind)}
            self.assertEqual(len(old_ids), expected)
            self.assertEqual(len(new_ids), expected)
            self.assertFalse(old_ids & new_ids)
        self.assertEqual(hashlib.sha256(b''.join(sorted(triple_digest(*t) for t in old_graph))).hexdigest(),
            'b47b622b8fcb99385b94c7aa3794569bad5822e83a42ed9e1b05a7b3e10d621a')

    def test_batch_preserves_typed_precision_missing_values_and_raw_provenance(self):
        graph = self.build()
        pond = URIRef(CSV_NS + 'instance:p1')
        prefix = CSV_NS + 'property:csv_ponds:'
        self.assertIn((pond, URIRef(prefix + 'area_m2'),
            Literal('123456789012345678.123456789', datatype=XSD.decimal, normalize=False)), graph)
        self.assertIn((pond, URIRef(prefix + 'reading_count'), Literal('0', datatype=XSD.integer)), graph)
        self.assertIn((pond, URIRef(prefix + 'published'), Literal(False)), graph)
        self.assertIn((pond, URIRef(prefix + 'observed_at'),
            Literal('2026-11-09T10:20:30Z', datatype=XSD.dateTime, normalize=False)), graph)
        self.assertFalse(list(graph.objects(pond, URIRef(prefix + 'mean_depth_m'))))
        self.assertIn((pond, URIRef(CSV_NS + 'missingField'), URIRef(prefix + 'mean_depth_m')), graph)
        source = URIRef(CSV_NS + 'source:csv_ponds:1')
        self.assertIn((pond, PROV.wasDerivedFrom, source), graph)
        self.assertIn((source, URIRef(CSV_NS + 'raw:csv_ponds:mean_depth_m'), Literal('')), graph)
        self.assertEqual(len(list(graph.subjects(RDF.type, URIRef(CSV_NS + 'SourceRecord')))), 3)

    def test_batch_relations_and_navigation_work_in_union_with_default_graph(self):
        graph = self.build()
        pond, farm = URIRef(CSV_NS + 'instance:p1'), URIRef(CSV_NS + 'instance:f1')
        relation = URIRef(CSV_NS + 'relation:csv_ponds:farm_id:csv_farms')
        inverse = URIRef(str(relation) + ':inverse')
        self.assertIn((relation, OWL.inverseOf, inverse), graph)
        self.assertIn((pond, relation, farm), graph)
        self.assertIn((farm, inverse, pond), graph)
        self.assertFalse(list(graph.objects(URIRef(CSV_NS + 'edge:2'), RDF.object)))
        for triple in project(fixture()): graph.add(triple)
        nav = self.navigation(graph)
        manifest, tables = nav.finish()
        self.assertEqual(manifest['namespace'], CSV_NS)
        self.assertEqual(manifest['counts']['instances'], 2)
        item = tables['csv_ponds']['instances'][0]
        self.assertEqual(item['adoption_status'], CSV_STATE)
        self.assertEqual(item['outgoing'][0]['target_iri'], str(farm))
        self.assertEqual(tables['csv_farms']['instances'][0]['incoming'][0]['source_iri'], str(pond))
        self.assertEqual(item['unresolved_relations'][0]['target_id'], 'F02')
        self.assertEqual(item['provenance']['source_record_iri'], CSV_NS + 'source:csv_ponds:1')
        self.assertEqual(item['provenance']['status'], 'needs_review')
        self.assertNotIn('payload', item['provenance'])
        self.assertFalse(any(str(p).startswith(CSV_NS + 'raw:')
            for predicates in nav.records.values() for p in predicates))
        wrong_state = Navigation(namespace=CSV_NS)
        for triple in graph: wrong_state.add(*triple)
        with self.assertRaises(ValueError): wrong_state.finish()

    def test_batch_shacl_checks_real_instances_and_detects_type_and_target_errors(self):
        graph = self.build()
        shape_graph = shapes(csv_fixture()['schema'], graph, namespace=CSV_NS)
        self.assertFalse(any(isinstance(term, URIRef) and str(term).startswith(NS)
            for triple in shape_graph for term in triple))
        nav = self.navigation(graph)
        events = []
        report = validate_canonical(nav, shape_graph, progress=events.append, namespace=CSV_NS)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['instances_validated'], 2)
        self.assertEqual(report['relation_class_constraints'], 2)
        self.assertEqual(len(events), 2)
        nav.records[CSV_NS + 'instance:p1'][CSV_NS + 'property:csv_ponds:area_m2'] = [Literal('invalid')]
        report = validate_canonical(nav, shape_graph, namespace=CSV_NS)
        self.assertEqual(report['status'], 'failed')
        self.assertGreater(report['violations'], 0)
        nav = self.navigation(graph)
        nav.records[CSV_NS + 'instance:p1'][CSV_NS + 'relation:csv_ponds:farm_id:csv_farms'] = [URIRef(CSV_NS + 'instance:p1')]
        self.assertEqual(validate_canonical(nav, shape_graph, namespace=CSV_NS)['status'], 'failed')

    def test_shacl_rejects_mismatched_namespace_instead_of_passing_zero_instances(self):
        graph = self.build()
        shape_graph = shapes(csv_fixture()['schema'], graph, namespace=CSV_NS)
        nav = self.navigation(graph)
        nav.records[CSV_NS + 'instance:p1'][CSV_NS + 'property:csv_ponds:area_m2'] = [Literal('invalid')]
        with self.assertRaises(ValueError):
            validate_canonical(nav, shape_graph)
        with self.assertRaises(ValueError):
            validate_canonical(nav, shape_graph, namespace='urn:wrong:')


if __name__ == '__main__':
    unittest.main()
