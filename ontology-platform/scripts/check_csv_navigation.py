"""Behavior checks for legacy, lazy-detail, and paged RDF navigation snapshots."""
from contextlib import redirect_stdout
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest

from verify_fish_rdf_navigation import verify


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False).encode('utf-8')
    path.write_bytes(gzip.compress(encoded, mtime=0) if path.name.endswith('.gz') else encoded)


def read_json(path):
    payload = path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.name.endswith('.gz') else payload)


def fixture(output, lazy=False, paged=False, edge_count=1):
    """Two real DTOs, one unresolved reference and one reversible demo link."""
    graph = 'urn:test:graph'
    a = dict(iri='urn:test:a', id='A', uuid='A', label='Alpha', class_iri='urn:test:class:a', table='csv_alpha',
             nature='synthetic', adoption_status='candidate_only', batch_id='test-batch',
             properties=[], provenance={'status': 'synthetic'}, outgoing=[], incoming=[],
             demo_assignments=[], unresolved_relations=[{'field': 'external_id', 'value': 'UNRESOLVED'}])
    b = dict(iri='urn:test:b', id='B', uuid='B', label='Beta', class_iri='urn:test:class:b', table='csv_beta',
             nature='synthetic', adoption_status='candidate_only', batch_id='test-batch',
             properties=[], provenance={'status': 'synthetic'}, outgoing=[], incoming=[],
             demo_assignments=[], unresolved_relations=[])
    for i in range(edge_count):
        common = dict(iri='urn:test:relation', edge_iri=f'urn:test:edge:{i}', field='target',
                      label='target', resolution='resolved', source_row=2, list_index=None)
        a['outgoing'].append(dict(common, target_iri=b['iri'], target_id='B', target_label='Beta', target_class_iri=b['class_iri']))
        b['incoming'].append(dict(common, source_iri=a['iri'], source_id='A', source_label='Alpha', source_class_iri=a['class_iri']))
    demo = dict(kind='activity', assignment_iri='urn:test:demo', relation_iri='urn:test:assignedTo',
                assignment_policy='balanced_demo_only', synthetic=True, reason='Demonstration only')
    a['demo_assignments'] = [dict(demo, direction='outgoing', target_iri=b['iri'], target_id='B', target_label='Beta', target_class_iri=b['class_iri'])]
    b['demo_assignments'] = [dict(demo, direction='incoming', source_iri=a['iri'], source_id='A', source_label='Alpha', source_class_iri=a['class_iri'])]
    data = output / 'data'
    if paged:
        for node, direction in [(a, 'outgoing'), (b, 'incoming')]:
            edges = node[direction]
            node[direction + '_count'] = len(edges)
            node[direction + '_page_size'] = 4800
            node[direction + '_pages'] = []
            for page in range(0, len(edges), 4800):
                name = f'relations/{node["table"]}/{node["id"]}/{direction}-{page // 4800 + 1:05}.json.gz'
                node[direction + '_pages'].append(name)
                write_json(data / name, dict(contract='fish-rdf-relations/1', instance_iri=node['iri'], direction=direction, edges=edges[page:page + 4800]))
            node[direction] = []
    concepts = [dict(iri='urn:test:root', label='Root', parent_iri=None,
                     children=[a['class_iri'], b['class_iri']], table=None, instance_count=0, total_instance_count=2, instances_path=None)]
    for node in [a, b]:
        table = node['table']
        if lazy:
            node['detail_path'] = f'details/{table}/00001.json.gz'
        shard = dict(contract='fish-rdf-review/1', class_iri=node['class_iri'], graph_iri=graph, jena_verified=True, instances=[node])
        if lazy:
            detail_path = f'details/{table}/00001.json.gz'
            write_json(data / detail_path, shard)
            summary = {k:node[k] for k in ['iri', 'id', 'uuid', 'label', 'class_iri', 'table', 'nature', 'adoption_status', 'batch_id']}
            summary['detail_path'] = detail_path
            shard = dict(shard, instances=[summary])
        write_json(data / f'classes/{table}.json.gz', shard)
        concepts.append(dict(iri=node['class_iri'], label=node['label'], parent_iri='urn:test:root', children=[],
                             table=table, instance_count=1, total_instance_count=1, instances_path=f'classes/{table}.json.gz'))
    manifest = dict(contract='fish-rdf-review/1', root_iri='urn:test:root', jena_verified=True, fuseki_readback=True,
                    rdf_graphs=[graph], concepts=concepts, counts=dict(instances=2, relations=edge_count + 1,
                    resolved_relations=edge_count, demo_assignments=1, classes=3))
    write_json(data / 'manifest.json', manifest)
    return a, b


class NavigationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='csv-navigation-')
        self.output = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def run_verify(self):
        with redirect_stdout(io.StringIO()):
            return verify(self.output)

    def mutate(self, name, change):
        path = self.output / 'data' / name
        value = read_json(path)
        change(value)
        write_json(path, value)

    def test_legacy_inline_navigation_still_preserves_unresolved_and_demo(self):
        fixture(self.output)
        before = {p:p.read_bytes() for p in (self.output / 'data').rglob('*') if p.is_file()}
        report = self.run_verify()
        self.assertEqual((report['instances_checked'], report['resolved_links_checked_both_directions'], report['unresolved_records_preserved'], report['demo_links_checked_both_directions']), (2, 1, 1, 1))
        self.assertEqual(set(report['shard_sha256']), {'csv_alpha', 'csv_beta'})
        self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))

    def test_legacy_map_percent_encoded_ids_match_unicode_source_ids(self):
        fixture(self.output)
        map_class='urn:lzo:fish-review:map:v1:class:Field'
        for path in (self.output / 'data').rglob('*'):
            if not path.is_file():
                continue
            value=read_json(path)
            value=json.loads(json.dumps(value).replace('urn:test:class:a', map_class))
            write_json(path, value)
        self.mutate('classes/csv_alpha.json.gz', lambda d:d['instances'][0].update(id='DRAW-旱地-M16'))
        def encoded(d):
            node=d['instances'][0]
            node['incoming'][0]['source_id']='DRAW-%E6%97%B1%E5%9C%B0-M16'
            node['demo_assignments'][0]['source_id']='DRAW-%E6%97%B1%E5%9C%B0-M16'
        self.mutate('classes/csv_beta.json.gz', encoded)
        self.assertEqual(self.run_verify()['resolved_links_checked_both_directions'], 1)

    def test_csv_source_ids_are_never_silently_url_decoded(self):
        fixture(self.output, lazy=True)
        self.mutate('details/csv_beta/00001.json.gz', lambda d:d['instances'][0]['incoming'][0].update(source_id='%41'))
        with self.assertRaises(ValueError):
            self.run_verify()

    def test_lazy_details_are_loaded_and_individually_hashed(self):
        fixture(self.output, lazy=True)
        report = self.run_verify()
        self.assertEqual(report['detail_file_count'], 2)
        self.assertEqual(report['detail_instances_checked'], 2)
        self.assertEqual(set(report['detail_sha256']), {'details/csv_alpha/00001.json.gz', 'details/csv_beta/00001.json.gz'})
        self.assertEqual(report['resolved_links_checked_both_directions'], 1)

    def test_rejects_incomplete_lazy_summary_contract(self):
        for field in ['label', 'nature', 'adoption_status', 'batch_id']:
            with self.subTest(field=field):
                fixture(self.output, lazy=True)
                self.mutate('classes/csv_alpha.json.gz', lambda d:d['instances'][0].pop(field))
                with self.assertRaises(ValueError):
                    self.run_verify()

    def test_relation_page_directory_must_match_its_owner(self):
        fixture(self.output, lazy=True, paged=True)
        old=self.output / 'data/relations/csv_alpha/A/outgoing-00001.json.gz'
        renamed=self.output / 'data/relations/csv_alpha/B/outgoing-00001.json.gz'
        renamed.parent.mkdir(parents=True, exist_ok=True)
        old.rename(renamed)
        self.mutate('details/csv_alpha/00001.json.gz', lambda d:d['instances'][0].update(outgoing_pages=['relations/csv_alpha/B/outgoing-00001.json.gz']))
        with self.assertRaises(ValueError):
            self.run_verify()

    def test_4800_edge_pages_are_read_in_both_directions(self):
        fixture(self.output, lazy=True, paged=True, edge_count=4801)
        report = self.run_verify()
        self.assertEqual(report['resolved_links_checked_both_directions'], 4801)
        self.assertEqual(report['relation_file_count'], 4)
        self.assertEqual(report['relation_edges_checked'], 9602)
        self.assertEqual(len(report['relation_sha256']), 4)

    def test_rejects_wrong_or_incomplete_detail_snapshots(self):
        mutations = {
            'wrong class': lambda d:d.update(class_iri='urn:wrong'),
            'wrong graph': lambda d:d.update(graph_iri='urn:wrong'),
            'unverified': lambda d:d.update(jena_verified=False),
            'wrong contract': lambda d:d.update(contract='other/1'),
            'missing row': lambda d:d.update(instances=[]),
            'duplicate row': lambda d:d['instances'].append(deepcopy(d['instances'][0])),
            'wrong IRI': lambda d:d['instances'][0].update(iri='urn:unknown'),
            'summary mismatch': lambda d:d['instances'][0].update(nature='real_field'),
            'raw payload': lambda d:d['instances'][0]['provenance'].update(raw_payload={'secret':'not public'}),
            'envelope raw payload': lambda d:d.update(rawpayload={'secret':'not public'}),
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                fixture(self.output, lazy=True)
                self.mutate('details/csv_alpha/00001.json.gz', mutation)
                with self.assertRaises(ValueError):
                    self.run_verify()

    def test_rejects_unsafe_detail_paths(self):
        for value in ['../outside.json.gz', '/tmp/outside.json.gz', 'C:/outside.json.gz', 'details/../classes/csv_alpha.json.gz', 'details\\csv_alpha\\00001.json.gz']:
            with self.subTest(path=value):
                fixture(self.output, lazy=True)
                self.mutate('classes/csv_alpha.json.gz', lambda d:d['instances'][0].update(detail_path=value))
                with self.assertRaises(ValueError):
                    self.run_verify()

    def test_rejects_missing_inverse_and_changed_relation_metadata(self):
        for mutation in [lambda d:d['instances'][0].update(incoming=[]),
                         lambda d:d['instances'][0]['incoming'][0].update(field='wrong'),
                         lambda d:d['instances'][0]['incoming'][0].update(source_class_iri='urn:wrong'),
                         lambda d:d['instances'][0]['incoming'][0].update(source_iri='urn:missing')]:
            fixture(self.output, lazy=True)
            self.mutate('details/csv_beta/00001.json.gz', mutation)
            with self.assertRaises(ValueError):
                self.run_verify()

    def test_rejects_duplicate_edges_and_invalid_demo_nature_or_direction(self):
        for mutation in [lambda d:d['instances'][0]['outgoing'].append(deepcopy(d['instances'][0]['outgoing'][0])),
                         lambda d:d['instances'][0]['demo_assignments'][0].update(synthetic=False),
                         lambda d:d['instances'][0]['demo_assignments'][0].update(direction='sideways'),
                         lambda d:d['instances'][0].update(demo_assignments=[])]:
            fixture(self.output, lazy=True)
            self.mutate('details/csv_alpha/00001.json.gz', mutation)
            with self.assertRaises(ValueError):
                self.run_verify()

    def test_rejects_same_edge_identity_repeated_with_changed_metadata(self):
        fixture(self.output, lazy=True)
        for table, direction in [('csv_alpha', 'outgoing'), ('csv_beta', 'incoming')]:
            def change(d):
                duplicate=deepcopy(d['instances'][0][direction][0])
                duplicate['field']='changed_duplicate'
                d['instances'][0][direction].append(duplicate)
            self.mutate(f'details/{table}/00001.json.gz', change)
        self.mutate('manifest.json', lambda d:d['counts'].update(resolved_relations=2, relations=3))
        with self.assertRaises(ValueError):
            self.run_verify()

    def test_rejects_unreferenced_detail_and_relation_files(self):
        for folder in ['details', 'relations']:
            with self.subTest(folder=folder):
                fixture(self.output, lazy=True)
                extra=self.output / 'data' / folder / 'orphan.json.gz'
                write_json(extra, {'contract':'unreferenced'})
                with self.assertRaises(ValueError):
                    self.run_verify()
                extra.unlink()

    def test_rejects_wrong_relation_page_identity_direction_count_and_target(self):
        mutations = [lambda d:d.update(direction='incoming'), lambda d:d.update(instance_iri='urn:test:b'),
                     lambda d:d.update(contract='other/1'), lambda d:d.update(edges=[]),
                     lambda d:d['edges'][0].update(target_class_iri='urn:wrong'),
                     lambda d:d['edges'][0].update(target_iri='urn:missing')]
        for mutation in mutations:
            fixture(self.output, lazy=True, paged=True)
            self.mutate('relations/csv_alpha/A/outgoing-00001.json.gz', mutation)
            with self.assertRaises(ValueError):
                self.run_verify()

    def test_rejects_missing_duplicate_and_unsafe_relation_pages(self):
        for mode in ['missing', 'duplicate', 'traversal']:
            with self.subTest(mode=mode):
                fixture(self.output, lazy=True, paged=True)
                if mode=='missing':
                    (self.output / 'data/relations/csv_alpha/A/outgoing-00001.json.gz').unlink()
                else:
                    def change(d):
                        item=d['instances'][0]
                        item['outgoing_pages'] = item['outgoing_pages'] * 2 if mode=='duplicate' else ['../outside.json.gz']
                    self.mutate('details/csv_alpha/00001.json.gz', change)
                with self.assertRaises(ValueError):
                    self.run_verify()


if __name__ == '__main__':
    unittest.main(verbosity=2)
