"""Executable RDF projection checks; no database or service needed."""
import unittest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD


def fixture():
    return {
        'package_sha256': 'a' * 64,
        'schema': {'tables': {
            'farms': {'columns': {'id': {'type': 'string'}, 'name': {'type': 'string'}}},
            'ponds': {'columns': {'id': {'type': 'string'}, 'area_m2': {'type': 'number', 'unit': 'm2'},
                'mean_depth_m': {'type': 'number', 'unit': 'm'}, 'farm_id': {'type': 'string'}}},
        }},
        'nodes': [
            {'node_id': 'f1', 'table_name': 'farms', 'source_pk': 'F01', 'role': 'entity', 'source_row': 1,
             'properties': {'id': 'F01', 'name': 'Farm'}, 'nature': 'synthetic'},
            {'node_id': 'p1', 'table_name': 'ponds', 'source_pk': 'P01', 'role': 'entity', 'source_row': 1,
             'properties': {'id': 'P01', 'area_m2': '123456789012345678.123456789', 'mean_depth_m': None,
                            'farm_id': 'F01'}, 'nature': 'synthetic'},
        ],
        'raw': [
            {'table_name': 'farms', 'row_number': 1, 'source_pk': 'F01', 'status': 'accepted',
             'payload': {'id': 'F01', 'name': 'Farm'}, 'issues': [], 'sample_reason': 'seed'},
            {'table_name': 'ponds', 'row_number': 1, 'source_pk': 'P01', 'status': 'needs_review',
             'payload': {'id': 'P01', 'area_m2': '123456789012345678.123456789', 'mean_depth_m': '',
                         'farm_id': 'F01'}, 'issues': [{'code': 'missing'}], 'sample_reason': 'seed'},
            {'table_name': 'ponds', 'row_number': 2, 'source_pk': 'P01', 'status': 'duplicate',
             'payload': {'id': 'P01', 'area_m2': '123456789012345678.123456789', 'mean_depth_m': '',
                         'farm_id': 'F01'}, 'issues': [], 'sample_reason': 'status_coverage'},
        ],
        'relations': [
            {'edge_id': 1, 'from_node': 'p1', 'field_name': 'farm_id', 'target_table': 'farms',
             'target_pk': 'F01', 'to_node': 'f1', 'resolution': 'resolved', 'source_row': 1, 'list_index': 0},
            {'edge_id': 2, 'from_node': 'p1', 'field_name': 'farm_id', 'target_table': 'farms',
             'target_pk': 'F02', 'to_node': None, 'resolution': 'unresolved', 'source_row': 1, 'list_index': 1},
        ],
    }


class ProjectionChecks(unittest.TestCase):
    def build(self, snapshot=None):
        from fish_rdf_sample import project
        graph = Graph()
        for triple in project(snapshot or fixture()):
            graph.add(triple)
        return graph

    def test_projection_is_available(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('fish_rdf_sample'))

    def test_real_type_hierarchy_and_precision_without_invented_null(self):
        from fish_rdf_sample import NS
        graph = self.build()
        pond = URIRef(NS + 'instance:p1')
        self.assertIn((pond, RDF.type, URIRef(NS + 'class:ponds')), graph)
        self.assertIn((URIRef(NS + 'class:ponds'), RDFS.subClassOf,
            URIRef('https://w3id.org/lzo/ontology/Pond')), graph)
        self.assertIn((pond, URIRef(NS + 'property:ponds:area_m2'),
            Literal('123456789012345678.123456789', datatype=XSD.decimal, normalize=False)), graph)
        self.assertFalse(list(graph.objects(pond, URIRef(NS + 'property:ponds:mean_depth_m'))))
        self.assertIn((pond, URIRef(NS + 'missingField'), URIRef(NS + 'property:ponds:mean_depth_m')), graph)

    def test_resolved_relation_and_inverse_are_real_triples_but_unresolved_has_no_target(self):
        from fish_rdf_sample import NS
        graph = self.build()
        relation = URIRef(NS + 'relation:ponds:farm_id:farms')
        inverse = URIRef(str(relation) + ':inverse')
        self.assertIn((relation, RDF.type, OWL.ObjectProperty), graph)
        self.assertIn((relation, OWL.inverseOf, inverse), graph)
        self.assertIn((URIRef(NS + 'instance:p1'), relation, URIRef(NS + 'instance:f1')), graph)
        self.assertIn((URIRef(NS + 'instance:f1'), inverse, URIRef(NS + 'instance:p1')), graph)
        self.assertFalse(list(graph.objects(URIRef(NS + 'edge:2'), RDF.object)))
        self.assertEqual(str(graph.value(URIRef(NS + 'edge:2'), URIRef(NS + 'targetPK'))), 'F02')

    def test_duplicates_and_raw_empty_strings_survive_without_duplicate_instances(self):
        from fish_rdf_sample import NS, PROV
        graph = self.build()
        self.assertEqual(len(list(graph.subjects(RDF.type, URIRef(NS + 'class:ponds')))), 1)
        self.assertEqual(len(list(graph.subjects(RDF.type, URIRef(NS + 'SourceRecord')))), 3)
        self.assertIn((URIRef(NS + 'source:ponds:2'), URIRef(NS + 'raw:ponds:mean_depth_m'), Literal('')), graph)
        self.assertIn((URIRef(NS + 'instance:p1'), PROV.wasDerivedFrom, URIRef(NS + 'source:ponds:1')), graph)
        self.assertEqual(str(graph.value(URIRef(NS + 'instance:p1'), URIRef(NS + 'adoptionStatus'))), 'sample_not_formally_adopted')

    def test_resolved_missing_or_wrong_class_target_is_rejected(self):
        data = fixture()
        data['relations'][0]['to_node'] = 'missing'
        with self.assertRaises(ValueError): self.build(data)
        data = fixture()
        data['relations'][0]['target_table'] = 'ponds'
        with self.assertRaises(ValueError): self.build(data)

    def test_snapshot_is_derived_from_rdf_with_usable_inverse_navigation_and_no_raw_payload(self):
        from fish_rdf_sample import Navigation, NS
        navigation = Navigation()
        for triple in self.build(): navigation.add(*triple)
        manifest, tables = navigation.finish()
        self.assertEqual(manifest['counts']['instances'], 2)
        pond = tables['ponds']['instances'][0]
        self.assertEqual(pond['outgoing'][0]['target_iri'], NS + 'instance:f1')
        self.assertEqual(tables['farms']['instances'][0]['incoming'][0]['source_iri'], NS + 'instance:p1')
        self.assertEqual(pond['provenance']['status'], 'needs_review')
        self.assertEqual(pond['unresolved_relations'][0]['target_id'], 'F02')
        self.assertNotIn('payload', pond['provenance'])
        self.assertIsNone(next(p['value'] for p in pond['properties'] if p['field'] == 'mean_depth_m'))

    def test_graph_writer_refuses_formal_graph_and_remote_endpoint(self):
        from build_fish_rdf_sample import check_target
        graph = 'urn:lzo:fish-review:sample:v1:graph:' + 'a' * 64 + ':' + 'b' * 64
        check_target('http://127.0.0.1:23049/fish_l1', graph)
        with self.assertRaises(ValueError):
            check_target('http://127.0.0.1:23049/fish_l1', 'urn:lzo:resource:formal:accepted')
        with self.assertRaises(ValueError):
            check_target('http://example.com:23049/fish_l1', graph)

    def test_complete_readback_rejects_altered_literal(self):
        from build_fish_rdf_sample import Readback
        from fish_rdf_sample import Navigation, triple_digest
        triple = (URIRef('urn:a'), URIRef('urn:p'), Literal('1.234567890123456789', datatype=XSD.decimal, normalize=False))
        sink = Readback({triple_digest(*triple)}, Navigation())
        with self.assertRaises(ValueError):
            sink.triple(triple[0], triple[1], Literal('1.2345678901234568', datatype=XSD.decimal, normalize=False))
        sink.triple(*triple)
        self.assertFalse(sink.remaining)

    def test_normalizer_extra_source_unit_is_retained_and_does_not_replace_typed_unit(self):
        from fish_rdf_sample import NS
        data = fixture()
        # Real source CSV contains explicitly documented extra unit columns.
        data['schema']['tables']['feeding_events'] = {'columns': {'id': {'type': 'string'},
            'quantity_kg': {'type': 'number', 'unit': 'kg'}}}
        data['nodes'].append({'node_id': 'feed', 'table_name': 'feeding_events', 'source_pk': 'X',
            'role': 'entity', 'source_row': 1, 'properties': {'id': 'X', 'quantity_kg': '12.3',
            'quantity_kg_unit': 'kg'}, 'nature': 'synthetic'})
        data['raw'].append({'table_name': 'feeding_events', 'row_number': 1, 'source_pk': 'X',
            'status': 'accepted', 'payload': {'id': 'X', 'quantity_kg': '12.3', 'quantity_kg_unit': 'kg'},
            'issues': [], 'sample_reason': 'seed'})
        graph = self.build(data)
        self.assertIn((URIRef(NS + 'instance:feed'), URIRef(NS + 'property:feeding_events:quantity_kg_unit'),
            Literal('kg', datatype=XSD.string)), graph)

    def test_decimal_canonical_lexical_preserves_more_than_context_precision(self):
        from fish_rdf_sample import typed_literal
        self.assertEqual(str(typed_literal('60', {'type': 'number'})), '60.0')
        self.assertEqual(str(typed_literal('60.5000', {'type': 'number'})), '60.5')
        self.assertEqual(str(typed_literal('123456789012345678901234567890.1234567890', {'type': 'number'})),
            '123456789012345678901234567890.123456789')

    def test_boolean_numeric_impostors_are_rejected(self):
        from fish_rdf_sample import typed_literal
        for value in (0, 1, 0.0, 1.0, '1', '0'):
            with self.assertRaises(ValueError): typed_literal(value, {'type': 'boolean'})

    def test_actual_shacl_detects_changed_value_type_and_wrong_target_class(self):
        from fish_rdf_sample import Navigation, NS
        from fish_rdf_validation import shapes, validate_canonical
        graph = self.build()
        shape_graph = shapes(fixture()['schema'], graph)
        navigation = Navigation()
        for triple in graph: navigation.add(*triple)
        self.assertEqual(validate_canonical(navigation, shape_graph)['status'], 'passed')
        navigation.records[NS + 'instance:p1'][NS + 'property:ponds:area_m2'] = [Literal('invalid')]
        report = validate_canonical(navigation, shape_graph)
        self.assertEqual(report['status'], 'failed')
        self.assertGreater(report['violations'], 0)
        navigation = Navigation()
        for triple in graph: navigation.add(*triple)
        navigation.records[NS + 'instance:p1'][NS + 'relation:ponds:farm_id:farms'] = [URIRef(NS + 'instance:p1')]
        self.assertEqual(validate_canonical(navigation, shape_graph)['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
