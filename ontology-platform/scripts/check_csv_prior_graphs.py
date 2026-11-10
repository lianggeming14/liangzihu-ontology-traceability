"""Offline checks for read-only preservation evidence; fixtures are synthetic."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs

import httpx

try:
    verifier = importlib.import_module('verify_csv_prior_graphs')
except ModuleNotFoundError:
    verifier = None


OLD_PACKAGE = '04891aab2039607015d41575e292a0add57065af3a2037270893cc0f3cd7c4b7'
NEW_PREFIX = 'urn:lzo:csv-batch:v1:a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524:graph:'
ENDPOINT = 'http://127.0.0.1:23049/fish_l1'
DECIMAL = 'http://www.w3.org/2001/XMLSchema#decimal'


def lexical_digest(value='12.3400'):
    # Independent RDF-term fixture: decimal lexical values remain exact text.
    terms = [['iri', 'urn:test:subject'], ['iri', 'urn:test:predicate'],
             ['literal', value, DECIMAL, '']]
    triple = hashlib.sha256(json.dumps(terms, ensure_ascii=False, separators=(',', ':')).encode()).digest()
    return hashlib.sha256(triple).hexdigest()


class PriorGraphChecks(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix='lzo-prior-graphs-')
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.baseline = self.root / '.runtime/baseline'
        self.baseline.mkdir(parents=True)
        self.reference = self.baseline / 'report.json'
        self.output = self.root / '.runtime/after'
        self.report = self.root / 'docs/csv-batch/prior-graphs-readback.json'
        digest = lexical_digest()
        self.graphs = ['urn:lzo:fish-review:sample:v1:graph:' + OLD_PACKAGE + ':' + digest,
                       'urn:lzo:fish-review:map:v1:graph:' + 'a' * 64,
                       'urn:lzo:fish-review:demo:v1:graph:' + 'b' * 64,
                       'urn:lzo:fish-review:drawing:v1:graph:' + 'c' * 64]
        self.reference_data = {'contract': 'csv-prior-graphs-baseline/1', 'status': 'passed',
            'mode': 'read_only', 'jena_endpoint': ENDPOINT, 'rdf_literal_normalization': False,
            'jena_nonempty_graph_count': 977, 'jena_non_review_graph_count': 971,
            'inventory_counts_unchanged_during_capture': True,
            'started_at': '2026-11-09T00:00:00+00:00', 'finished_at': '2026-11-09T00:00:01+00:00',
            'postgres': {'database': 'lzo_gis', 'server_port': 25449, 'transaction_read_only': 'on',
                         'review_raw_records': 20606, 'password': 'DO-NOT-PUBLISH'},
            'graphs': [{'graph_iri': graph, 'sparql_count': 1, 'parsed_triples': 1, 'unique_triples': 1,
                        'rdf_termset_sha256': digest, 'download_sha256': 'd' * 64,
                        'download_bytes': 100, 'termset_status': 'passed'} for graph in self.graphs]}
        self.inventory = {graph: 1 for graph in self.graphs}
        for index in range(971):
            self.inventory['urn:test:formal:' + str(index)] = 1
        for suffix in ('e', 'f'):
            self.inventory['urn:lzo:fish-review:sample:v1:graph:' + OLD_PACKAGE + ':' + suffix * 64] = 1
        self.write_baseline()
        self.nt = ('<urn:test:subject> <urn:test:predicate> "12.3400"^^<' + DECIMAL + '> .\n').encode()

    def impl(self):
        self.assertIsNotNone(verifier, 'Read-only prior-graph verifier is not implemented')
        return verifier

    def write_baseline(self):
        self.reference.write_text(json.dumps(self.reference_data), encoding='utf-8')
        (self.baseline / 'graph-inventory.json').write_text(json.dumps(self.inventory), encoding='utf-8')

    def transport(self, *, inventories=None, content=None):
        inventories = iter(inventories or [self.inventory, self.inventory])
        source = content or {graph: self.nt for graph in self.graphs}

        def handle(request):
            self.assertEqual(str(request.url).split('/fish_l1')[0], 'http://127.0.0.1:23049')
            if request.url.path == '/fish_l1/query':
                self.assertEqual(request.method, 'POST')
                query = parse_qs(request.content.decode())['query'][0]
                self.assertTrue(query.startswith('SELECT '), 'Only SELECT queries are allowed')
                rows = [{'g': {'type': 'uri', 'value': graph}, 'n': {'type': 'literal', 'value': str(n)}}
                        for graph, n in next(inventories).items()]
                return httpx.Response(200, json={'head': {'vars': ['g', 'n']}, 'results': {'bindings': rows}})
            self.assertEqual((request.method, request.url.path), ('GET', '/fish_l1/data'),
                             'No RDF write requests are authorized')
            graph = request.url.params['graph']
            self.assertIn(graph, self.graphs, 'Graphs must come only from the reference')
            return httpx.Response(200, content=source[graph], headers={'Content-Type': 'application/n-triples'})
        return httpx.MockTransport(handle)

    def run_verify(self, **kwargs):
        return self.impl().verify(self.reference, self.output, self.report, root=self.root,
                                  transport=kwargs.pop('transport', self.transport()), **kwargs)

    def test_private_output_guard_prevents_baseline_overwrite_and_public_nt(self):
        for output in (self.root / 'docs/public', self.root / '.runtime', self.baseline,
                       self.baseline / 'after', self.root / '.runtime/baseline/../'):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    self.impl().validate_paths(self.reference, output, self.report, root=self.root)
        self.assertFalse(self.report.exists())
        self.assertFalse(self.output.exists())

    def test_remote_endpoint_or_incomplete_reference_cannot_yield_success(self):
        for key, value in (('jena_endpoint', 'http://example.org/fish_l1'), ('status', 'running'),
                           ('inventory_counts_unchanged_during_capture', False), ('graphs', self.reference_data['graphs'][:3])):
            with self.subTest(key=key):
                data = copy.deepcopy(self.reference_data)
                data[key] = value
                self.reference.write_text(json.dumps(data), encoding='utf-8')
                result = self.run_verify()
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(json.loads(self.report.read_text())['status'], 'failed')

    def test_changed_missing_or_unapproved_new_graphs_fail_inventory_comparison(self):
        for change in ('changed', 'missing', 'foreign', 'wrong_package', 'prefix_lookalike'):
            with self.subTest(change=change):
                actual = dict(self.inventory)
                if change == 'changed':
                    actual['urn:test:formal:0'] = 2
                elif change == 'missing':
                    del actual['urn:test:formal:0']
                else:
                    prefix = {'foreign': 'urn:unexpected:graph:',
                              'wrong_package': NEW_PREFIX.replace('a4d78b', 'b4d78b'),
                              'prefix_lookalike': NEW_PREFIX + 'unsafe:'}[change]
                    actual[prefix + '1' * 64] = 9
                with self.assertRaises(ValueError):
                    self.impl().compare_inventory(self.inventory, actual)

    def test_exact_new_batch_graph_is_allowed_without_relaxing_old_counts(self):
        actual = dict(self.inventory)
        actual[NEW_PREFIX + '1' * 64] = 42
        evidence = self.impl().compare_inventory(self.inventory, actual)
        self.assertEqual(evidence['old_graph_count'], 977)
        self.assertTrue(evidence['old_graph_counts_unchanged'])
        self.assertEqual(evidence['additional_graphs'], [{'graph_iri': NEW_PREFIX + '1' * 64, 'triple_count': 42}])

    def test_lexical_precision_changes_are_detected_after_real_nt_parsing(self):
        self.output.mkdir(parents=True)
        path = self.output / 'precision.nt'
        path.write_bytes(self.nt)
        result = self.impl().termset_file(path)
        self.assertEqual(result['rdf_termset_sha256'], lexical_digest())
        self.assertEqual((result['parsed_triples'], result['unique_triples']), (1, 1))
        path.write_bytes(self.nt.replace(b'12.3400', b'12.34'))
        self.assertNotEqual(self.impl().termset_file(path)['rdf_termset_sha256'], lexical_digest())

    def test_duplicate_blank_node_and_invalid_rdf_fail_without_returning_raw_cells(self):
        self.output.mkdir(parents=True)
        path = self.output / 'invalid.nt'
        for content in (self.nt + self.nt, b'_:node <urn:test:p> "cell" .\n', b'SECRET-RAW-CELL invalid RDF\n'):
            with self.subTest(content=content):
                path.write_bytes(content)
                with self.assertRaises(ValueError) as failure:
                    self.impl().termset_file(path)
                self.assertNotIn('SECRET-RAW-CELL', str(failure.exception))

    def test_full_readback_uses_all_four_reference_graphs_and_only_publishes_evidence(self):
        actual = dict(self.inventory)
        actual[NEW_PREFIX + '1' * 64] = 42
        result = self.run_verify(transport=self.transport(inventories=[actual, actual]))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual([entry['graph_iri'] for entry in result['graphs']], self.graphs)
        self.assertTrue(all(entry['status'] == 'passed' for entry in result['graphs']))
        self.assertEqual(result['baseline']['source_archive_sha256'], OLD_PACKAGE)
        self.assertEqual(result['baseline']['reference_report_sha256'], hashlib.sha256(self.reference.read_bytes()).hexdigest())
        public = self.report.read_text(encoding='utf-8')
        self.assertNotIn('DO-NOT-PUBLISH', public)
        self.assertNotIn('12.3400', public)
        self.assertNotIn('urn:test:subject', public)
        self.assertEqual(len(list(self.output.glob('*.nt'))), 4)
        self.assertFalse(list((self.root / 'docs').rglob('*.nt')))

    def test_altered_termset_marks_failure_even_when_all_inventory_counts_match(self):
        content = {graph: self.nt for graph in self.graphs}
        content[self.graphs[1]] = self.nt.replace(b'12.3400', b'12.3401')
        result = self.run_verify(transport=self.transport(content=content))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['graphs']), 4, 'Readback must cover the other old graphs after a mismatch')
        self.assertEqual(result['graphs'][1]['status'], 'failed')
        self.assertEqual(result['graphs'][1]['expected_rdf_termset_sha256'], lexical_digest())

    def test_inventory_change_during_capture_cannot_be_reported_as_passed(self):
        changed = dict(self.inventory)
        changed['urn:test:formal:9'] = 2
        result = self.run_verify(transport=self.transport(inventories=[self.inventory, changed]))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(json.loads(self.report.read_text())['status'], 'failed')

    def test_failed_rerun_replaces_stale_passed_report_without_raw_error_text(self):
        self.report.parent.mkdir(parents=True)
        self.report.write_text('{"status":"passed"}', encoding='utf-8')
        content = {graph: b'SECRET-RAW-CELL is not NTriples\n' for graph in self.graphs}
        result = self.run_verify(transport=self.transport(content=content))
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('SECRET-RAW-CELL', self.report.read_text())
        self.assertEqual(json.loads(self.report.read_text())['status'], 'failed')

    def test_changed_or_missing_baseline_inventory_is_rejected(self):
        path = self.baseline / 'graph-inventory.json'
        del self.inventory[self.graphs[0]]
        self.write_baseline()
        self.assertEqual(self.run_verify()['status'], 'failed')
        path.unlink()
        self.assertEqual(self.run_verify()['status'], 'failed')

    def test_cli_rejects_public_output_before_contacting_service(self):
        script = Path(__file__).with_name('verify_csv_prior_graphs.py')
        self.impl()
        result = subprocess.run([sys.executable, str(script), '--reference', str(self.reference),
                                 '--output', str(self.root / 'public'), '--report', str(self.report)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'public').exists())
        self.assertFalse(self.report.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
