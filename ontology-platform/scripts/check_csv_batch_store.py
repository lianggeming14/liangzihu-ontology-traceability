"""Offline tests for the create-only PostgreSQL CSV batch receiver."""
import copy
from datetime import datetime, timezone
from decimal import Decimal
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

try:
    store = importlib.import_module('csv_batch_store')
except ModuleNotFoundError:
    store = None

PACKAGE = 'a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524'
SCHEMA = 'csv_batch_a4d78be79a83'


def fixture():
    schema = {'tables': {'farms': {'columns': {'id': {'type': 'string'}, 'name': {'type': 'string'}},
        'primary_key': ['id'], 'path': 'csv/farms.csv'}, 'observations': {'columns': {
            'id': {'type': 'string'}, 'farm_id': {'type': 'string'}, 'value': {'type': 'number'},
            'enabled': {'type': 'boolean'}, 'observed_at': {'type': 'string', 'format': 'date-time'}},
        'primary_key': ['id'], 'path': 'csv/observations.csv'}}}
    raw = [{'table_name': 'farms', 'row_number': 1, 'source_pk': '0001',
            'payload': {'id': '0001', 'name': 'source\nname'}, 'status': 'accepted', 'issues': [],
            'sample_reason': 'full_csv_batch'}, {'table_name': 'observations', 'row_number': 1,
            'source_pk': '0002', 'payload': {'id': '0002', 'farm_id': '0001', 'value': '12.3400',
            'enabled': 'true', 'observed_at': '2025-01-01T08:00:00+08:00'}, 'status': 'accepted',
            'issues': [], 'sample_reason': 'full_csv_batch'}]
    nodes = [{'node_id': '00000000-0000-4000-8000-000000000001', 'table_name': 'farms', 'source_pk': '0001',
              'source_row': 1, 'properties': {'id': '0001', 'name': 'source\nname'}, 'nature': 'synthetic', 'role': 'entity'},
             {'node_id': '00000000-0000-4000-8000-000000000002', 'table_name': 'observations', 'source_pk': '0002',
              'source_row': 1, 'properties': {'id': '0002', 'farm_id': '0001', 'value': '12.3400', 'enabled': True,
              'observed_at': '2025-01-01T08:00:00+08:00'}, 'nature': 'synthetic', 'role': 'telemetry'}]
    relations = [{'edge_id': 1, 'from_node': nodes[1]['node_id'], 'field_name': 'farm_id', 'target_table': 'farms',
                  'target_pk': '0001', 'to_node': nodes[0]['node_id'], 'resolution': 'resolved', 'source_row': 1,
                  'list_index': 0, 'evidence': 'explicit source FK'}]
    rules = [{'kind': 'scalar', 'source_table': 'observations', 'field': 'farm_id', 'target_table': 'farms',
              'target_field': 'id', 'missing_target_count': 0, 'evidence': 'explicit source FK'}]
    return {'package_sha256': PACKAGE, 'source_schema': SCHEMA, 'schema': schema,
            'raw': raw, 'nodes': nodes, 'relations': relations}, rules


class StoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store, 'csv_batch_store implementation is missing')

    def test_guard_allows_only_the_pinned_loopback_database_and_schema(self):
        good = 'postgresql+psycopg://lzo_gis_owner:fixture-only@127.0.0.1:25449/lzo_gis'
        store.guard_target(good, SCHEMA, PACKAGE)
        for bad in (good.replace('25449', '5432'), good.replace('127.0.0.1', 'localhost'),
                    good.replace('/lzo_gis', '/lzo'), good.replace('lzo_gis_owner', 'lzo_gis_app'),
                    good + '?options=-csearch_path=public', good.replace('postgresql+psycopg', 'sqlite')):
            with self.subTest(target=bad.split('@')[-1]):
                with self.assertRaises(ValueError) as caught:
                    store.guard_target(bad, SCHEMA, PACKAGE)
                self.assertNotIn('fixture-only', str(caught.exception))
        for schema, package in (('public', PACKAGE), (SCHEMA, '0' * 64), (SCHEMA + ';DROP', PACKAGE)):
            with self.assertRaises(ValueError):
                store.guard_target(good, schema, package)

    def test_server_guard_accepts_postgresql_loopback_host_mask_only(self):
        self.assertTrue(callable(getattr(store, 'guard_server', None)), 'Server identity guard is missing')
        for host in ('127.0.0.1', '127.0.0.1/32'):
            store.guard_server(('lzo_gis', 'lzo_gis_owner', host, 25449))
        for host in ('127.0.0.2/32', '127.0.0.1/8', 'localhost'):
            with self.assertRaises(ValueError):
                store.guard_server(('lzo_gis', 'lzo_gis_owner', host, 25449))

    def test_numeric_conversion_keeps_full_precision_and_refuses_float_nan(self):
        text = '1234567890123456789012345678901234567890.123456789012345678901234567890'
        self.assertEqual(store.typed_value(text, {'type': 'number'}), Decimal(text))
        self.assertEqual(str(store.typed_value('12.3400', {'type': 'number'})), '12.3400')
        for value in (0.1, True, 'NaN', 'Infinity'):
            with self.assertRaises(ValueError):
                store.typed_value(value, {'type': 'number'})
        with self.assertRaises(ValueError):
            store.typed_value('1.5', {'type': 'integer'})

    def test_bool_timestamp_and_text_do_not_use_lossy_coercion(self):
        self.assertIs(store.typed_value(True, {'type': 'boolean'}), True)
        with self.assertRaises(ValueError):
            store.typed_value('false', {'type': 'boolean'})
        self.assertEqual(store.typed_value('0001', {'type': 'string'}), '0001')
        self.assertIsNone(store.typed_value(None, {'type': 'number'}))
        self.assertEqual(store.typed_value('2025-01-01T08:00:00+08:00', {'format': 'date-time'}),
                         datetime(2025, 1, 1, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            store.typed_value('2025-01-01T08:00:00', {'format': 'date-time'})
        with self.assertRaises(ValueError):
            store.typed_value('2025-01-01T08:00:00.1234567+08:00', {'format': 'date-time'})

    def test_replay_identity_changes_for_schema_rules_raw_or_ledger_changes(self):
        snapshot, rules = fixture()
        first = store.identity(snapshot, rules)
        self.assertEqual(first, store.identity(copy.deepcopy(snapshot), copy.deepcopy(rules)))
        for kind in ('schema', 'raw', 'relations'):
            changed = copy.deepcopy(snapshot)
            if kind == 'schema':
                changed['schema']['tables']['farms']['columns']['name']['description'] = 'new definition'
            elif kind == 'raw':
                changed['raw'][0]['payload']['name'] = 'different original text'
            else:
                changed['relations'][0]['evidence'] = 'different source rule'
            self.assertNotEqual(first, store.identity(changed, rules))
        changed_rules = copy.deepcopy(rules)
        changed_rules[0]['evidence'] = 'different rule review'
        self.assertNotEqual(first, store.identity(snapshot, changed_rules))
        completed = {**first, 'physical_schema_sha256': '1' * 64}
        store.assert_identity(completed, first)
        with self.assertRaises(ValueError):
            store.assert_identity({**completed, 'complete': False}, first)
        with self.assertRaises(ValueError):
            store.assert_identity({**completed, 'snapshot_sha256': '0' * 64}, first)

    def test_partial_fixture_is_rejected_before_database_write(self):
        snapshot, _ = fixture()
        with self.assertRaises(ValueError):
            store.validate_snapshot(snapshot, require_full_batch=True)

    def test_driver_failures_produce_failed_receipts_without_private_text(self):
        cli = importlib.import_module('build_csv_database')
        self.assertTrue(callable(getattr(cli, 'failure_report', None)), 'Failure receipt implementation is missing')
        report = cli.failure_report(ValueError('private-value postgresql://password'))
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['operation_completed'])
        self.assertNotIn('private-value', json.dumps(report))
        self.assertNotIn('password', json.dumps(report))

    def test_plan_has_native_numeric_timestamptz_and_source_node_foreign_keys(self):
        snapshot, rules = fixture()
        plan = store.structure(snapshot, rules)
        ddl = '\n'.join(plan['statements'])
        self.assertIn('"value" NUMERIC', ddl)
        self.assertNotIn('NUMERIC(', ddl)
        self.assertIn('TIMESTAMP WITH TIME ZONE', ddl)
        self.assertIn('"enabled" BOOLEAN', ddl)
        self.assertIn('FOREIGN KEY ("table_name", "source_row")', ddl)
        self.assertIn('FOREIGN KEY ("from_node", "from_table", "source_row")', ddl)
        self.assertIn('FOREIGN KEY ("to_node", "target_table", "target_pk")', ddl)
        self.assertNotIn('DROP ', ddl)
        self.assertNotIn('TRUNCATE ', ddl)
        self.assertNotIn('source\nname', ddl)

    def test_invalid_source_identity_and_unresolved_bound_target_are_rejected(self):
        snapshot, rules = fixture()
        changed = copy.deepcopy(snapshot)
        changed['relations'][0]['resolution'] = 'unresolved'
        with self.assertRaises(ValueError):
            store.validate_snapshot(changed)
        changed = copy.deepcopy(snapshot)
        changed['nodes'][0]['source_row'] = 2
        with self.assertRaises(ValueError):
            store.validate_snapshot(changed)
        changed = copy.deepcopy(snapshot)
        changed['schema']['tables']['farms']['columns']['bad;sql'] = {'type': 'string'}
        with self.assertRaises(ValueError):
            store.structure(changed, rules)

    def test_readback_comparison_checks_every_record_and_never_reports_cells(self):
        expected = [(1, {'id': '0001', 'secret-note': 'private-value'}), (2, {'id': '0002'})]
        same = store.compare_rows(iter(expected), iter(expected), 'raw')
        self.assertEqual(same['status'], 'passed')
        for actual in (expected[:1], [*expected, (3, {})], [(1, {'id': 'changed'}), expected[1]]):
            report = store.compare_rows(iter(expected), iter(actual), 'raw')
            self.assertEqual(report['status'], 'failed')
            self.assertNotIn('private-value', json.dumps(report))
            self.assertNotIn('secret-note', json.dumps(report))

    def test_cli_exposes_explicit_apply_and_read_only_verify_modes(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('build_csv_database.py')), '--help'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--apply', result.stdout)
        self.assertIn('--verify', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
