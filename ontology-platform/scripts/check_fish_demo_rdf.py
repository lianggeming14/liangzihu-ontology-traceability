"""Demo relationship invariants: balance, provenance, no source mutation."""
import copy
import unittest
from collections import Counter
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, OWL

from fish_demo_rdf import assignments, project_demo, DemoNavigation, D


def fixture():
    def item(iri, pk, table, props=None):
        return {'iri': iri, 'id': pk, 'label': pk, 'class_iri': 'urn:class:' + table,
            'table': table, 'nature': 'synthetic' if not table.startswith('map_') else 'imported_unverified',
            'properties': props or []}
    tables = {
        'ponds': {'instances': [item('urn:pond:' + str(i), 'P0' + str(i), 'ponds') for i in range(1, 7)]},
        'map_pond': {'instances': [item(f'urn:map:{i:02}', f'M{i:02}', 'map_pond') for i in range(20)]},
        'feeding_events': {'instances': [item(f'urn:feed:{i:02}', f'F{i:02}', 'feeding_events',
            [{'field': 'pond_id', 'value': 'P01'}]) for i in range(43)]},
    }
    payload = {'objects': [{'object_iri': f'urn:map:{i:02}', 'asset_id': 'drawing-1', 'kind': 'pond'} for i in range(20)]}
    return tables, payload


class DemoChecks(unittest.TestCase):
    def test_per_table_round_robin_and_profile_balance_keep_original_values(self):
        tables, payload = fixture()
        before = copy.deepcopy(tables)
        items, counts = assignments(tables, payload)
        self.assertEqual(tables, before)
        self.assertEqual(len(items), 63)
        self.assertEqual(sorted(counts['feeding_events'].values()), [2] * 17 + [3] * 3)
        profiles = Counter(item['target'] for item in items if item['kind'] == 'pond_profile')
        self.assertEqual(sorted(profiles.values()), [3, 3, 3, 3, 4, 4])
        self.assertTrue(all(item['original_pond_id'] == 'P01' for item in items if item['kind'] == 'activity'))

    def test_readback_navigation_separates_demo_from_source_relations(self):
        tables, payload = fixture()
        items, _ = assignments(tables, payload)
        graph = Graph()
        navigation = DemoNavigation()
        for triple in project_demo(items): graph.add(triple)
        self.assertFalse(list(graph.triples((None, OWL.sameAs, None))))
        for triple in graph: navigation.add(*triple)
        self.assertEqual(navigation.apply(tables), {'activity': 43, 'pond_profile': 20})
        record = tables['feeding_events']['instances'][0]
        self.assertNotIn('outgoing', record)
        self.assertEqual(record['demo_assignments'][0]['assignment_policy'], 'balanced_demo_only')
        self.assertTrue(record['demo_assignments'][0]['synthetic'])
        self.assertEqual(record['properties'], [{'field': 'pond_id', 'value': 'P01'}])

    def test_missing_pond_fk_or_non_synthetic_record_does_not_receive_assignment(self):
        tables, payload = fixture()
        tables['feeding_events']['instances'][0]['properties'] = []
        tables['feeding_events']['instances'][1]['nature'] = 'imported_unverified'
        items, _ = assignments(tables, payload)
        self.assertEqual(sum(item['kind'] == 'activity' for item in items), 41)

    def test_incomplete_drawing_pond_set_is_rejected(self):
        tables, payload = fixture()
        payload['objects'].pop()
        with self.assertRaises(ValueError): assignments(tables, payload)


if __name__ == '__main__': unittest.main()
