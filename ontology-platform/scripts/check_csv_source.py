"""Stdlib regression checks for private, lossless CSV ZIP source reception."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

try:
    receiver = importlib.import_module('prepare_csv_batch')
except ModuleNotFoundError:
    receiver = None


class SourceReceptionTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix='lzo-csv-source-')
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.archive = self.root / 'source.zip'
        self.output = self.root / 'extracted'

    def package(self, entries, compression=zipfile.ZIP_STORED):
        raw_names = []
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w', compression=compression) as stream:
                for name, content in entries:
                    stream.writestr(name, content)
                    if isinstance(name, str) and '\\' in name:
                        raw_names.append((name.replace('\\', '/'), name))
        # ZipInfo normalizes backslashes when writing on Windows. Put the raw
        # hostile filename in both ZIP headers so the receiver sees real bytes.
        if raw_names:
            data = self.archive.read_bytes()
            for normalized, original in raw_names:
                data = data.replace(normalized.encode('utf-8'), original.encode('utf-8'))
            self.archive.write_bytes(data)

    def receive(self, **overrides):
        self.assertIsNotNone(receiver, 'prepare_csv_batch implementation is missing')
        data = self.archive.read_bytes()
        expected = {'expected_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
                    'expected_size': len(data)}
        expected.update(overrides)
        return receiver.prepare(self.archive, self.output, **expected)

    def reject(self):
        with self.assertRaises(ValueError):
            self.receive()
        self.assertFalse(self.output.exists(), 'Rejected source must create no extraction directory')

    def test_cells_remain_exact_text_and_quoted_newline_remains_one_record(self):
        content = b'\xef\xbb\xbfid,amount,note\r\n0007,12.3400,"line one\nline two"\r\n\r\n0008,,ok\r\n'
        self.package([('csv/records.csv', content), ('notes.txt', b'source notes')])
        manifest = self.receive()
        self.assertEqual((self.output / 'csv/records.csv').read_bytes(), content)
        member = manifest['members'][0]
        self.assertEqual(member['header'], ['id', 'amount', 'note'])
        self.assertEqual((member['row_count'], member['blank_rows'], member['bad_rows']), (2, 1, 0))
        self.assertEqual(member['encoding'], 'utf-8-sig')
        self.assertNotIn('line one', json.dumps(manifest))
        self.assertNotIn('12.3400', json.dumps(manifest))

    def test_appledouble_and_macosx_members_are_hashed_metadata_not_csv(self):
        sidecar = b'\x00\x05\x16\x07\x00\x02\x00\x00metadata'
        self.package([('csv/records.csv', b'id\n0001\n'),
                      ('__MACOSX/csv/._records.csv', sidecar),
                      ('csv/._other.csv', sidecar),
                      ('__MACOSX/unusual.csv', b'id\nnot a business record\n')])
        manifest = self.receive()
        self.assertEqual((manifest['csv_file_count'], manifest['row_count'], manifest['bad_rows']), (1, 1, 0))
        self.assertEqual(manifest['csv_status'], 'passed')
        self.assertEqual(manifest['metadata_file_count'], 3)
        self.assertEqual(manifest['encodings'], {'utf-8': 1})
        for item in manifest['members'][1:]:
            self.assertFalse(item['is_csv'])
            self.assertEqual(item['member_role'], 'metadata')
            self.assertEqual(len(item['sha256']), 64)
            self.assertNotIn('bad_rows', item)
            self.assertEqual((self.output / item['path']).stat().st_size, item['bytes'])

    def test_report_can_refresh_derived_metadata_only_for_identical_source_bytes(self):
        self.package([('csv/records.csv', b'id\n0001\n')])
        manifest = self.receive()
        report = self.root / 'report.json'
        previous = json.loads(json.dumps(manifest))
        previous['csv_file_count'] = 999
        report.write_text(json.dumps(previous), encoding='utf-8')
        self.assertTrue(callable(getattr(receiver, '_write_report', None)), 'Report refresh implementation is missing')
        receiver._write_report(report, manifest)
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['csv_file_count'], 1)
        previous['members'][0]['sha256'] = '0' * 64
        report.write_text(json.dumps(previous), encoding='utf-8')
        old_bytes = report.read_bytes()
        with self.assertRaises(ValueError):
            receiver._write_report(report, manifest)
        self.assertEqual(report.read_bytes(), old_bytes)

    def test_bad_widths_are_reported_without_losing_other_rows(self):
        self.package([('records.csv', b'id,value\n1,a\n2\n3,b,c\n4,d\n')])
        member = self.receive()['members'][0]
        self.assertEqual((member['row_count'], member['valid_rows'], member['bad_rows']), (4, 2, 2))
        self.assertEqual([item['line_start'] for item in member['bad_row_details']], [3, 4])
        self.assertEqual(member['status'], 'invalid_csv')

    def test_duplicate_and_empty_headers_are_explicitly_invalid(self):
        self.package([('records.csv', b'id,id, \n1,2,3\n')])
        member = self.receive()['members'][0]
        self.assertFalse(member['header_valid'])
        self.assertIn('duplicate_header', member['header_issues'])
        self.assertIn('empty_header', member['header_issues'])

    def test_strict_parser_reports_unclosed_quote(self):
        self.package([('records.csv', b'id,note\n1,"unterminated\n')])
        member = self.receive()['members'][0]
        self.assertEqual(member['bad_rows'], 1)
        self.assertFalse(member['row_count_complete'])
        self.assertEqual(member['bad_row_details'][0]['code'], 'csv_parse_error')

    def test_gb18030_is_marked_only_after_strict_roundtrip(self):
        self.package([('records.csv', 'id,说明\n0001,鱼塘𠀀\n'.encode('gb18030'))])
        member = self.receive()['members'][0]
        self.assertEqual(member['encoding'], 'gb18030')
        self.assertEqual(member['header'], ['id', '说明'])
        self.assertEqual(member['row_count'], 1)

    def test_invalid_csv_encoding_is_reported_without_guessing_cells(self):
        self.package([('records.csv', b'id,note\n1,\xff\xff\n')])
        member = self.receive()['members'][0]
        self.assertEqual(member['status'], 'invalid_csv')
        self.assertIsNone(member['encoding'])
        self.assertIn('unsupported_encoding', member['header_issues'])

    def test_utf8_bom_never_falls_back_to_gb18030_for_mixed_bytes(self):
        self.package([('records.csv', b'\xef\xbb\xbfid,note\n1,\xc4\xe3\n')])
        member = self.receive()['members'][0]
        self.assertEqual(member['status'], 'invalid_csv')
        self.assertIsNone(member['encoding'])
        self.assertIn('unsupported_encoding', member['header_issues'])

    def test_traversal_and_windows_names_fail_before_any_file_is_written(self):
        for name in ('../escape.csv', '/absolute.csv', 'a/../../escape.csv', 'a\\escape.csv',
                     'C:/escape.csv', 'a//records.csv', './records.csv', 'CON.csv', 'a/NUL',
                     'COM1.txt', 'CONIN$.csv', 'CON .csv', 'a/trailing. ', 'a/name?.csv', 'a/name:stream.csv'):
            with self.subTest(name=name):
                self.package([('safe.csv', b'id\n1\n'), (name, b'id\n2\n')])
                self.reject()
        self.assertFalse((self.root / 'escape.csv').exists())

    def test_duplicate_and_case_colliding_members_are_rejected(self):
        for names in (('a.csv', 'a.csv'), ('a.csv', 'A.csv'), ('Folder/a.csv', 'folder/b.csv')):
            with self.subTest(names=names):
                self.package([(name, b'id\n1\n') for name in names])
                self.reject()

    def test_file_directory_conflicts_are_rejected(self):
        self.package([('a', b'ordinary file'), ('a/records.csv', b'id\n1\n')])
        self.reject()

    def test_symlink_member_is_rejected(self):
        info = zipfile.ZipInfo('link.csv')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.package([(info, b'../outside')])
        self.reject()

    def test_encrypted_flag_is_rejected(self):
        self.package([('records.csv', b'id\n1\n')])
        data = bytearray(self.archive.read_bytes())
        local = data.index(b'PK\x03\x04')
        central = data.index(b'PK\x01\x02')
        struct.pack_into('<H', data, local + 6, 1)
        struct.pack_into('<H', data, central + 8, 1)
        self.archive.write_bytes(data)
        self.reject()

    def test_crc_mismatch_is_rejected_before_any_extraction(self):
        self.package([('safe.csv', b'id\n1\n'), ('broken.csv', b'id\n2\n')])
        data = bytearray(self.archive.read_bytes())
        where = data.index(b'id\n2\n')
        data[where + 3] = ord('3')
        self.archive.write_bytes(data)
        self.reject()

    def test_archive_blob_and_size_are_verified(self):
        self.package([('records.csv', b'id\n1\n')])
        for overrides in ({'expected_blob': '0' * 40}, {'expected_size': self.archive.stat().st_size + 1}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.receive(**overrides)
                self.assertFalse(self.output.exists())

    def test_high_compression_ratio_is_rejected_before_extraction(self):
        self.package([('records.csv', b'id\n' + b'0000\n' * 100000)], zipfile.ZIP_DEFLATED)
        self.reject()

    def test_identical_replay_reuses_bytes_and_changed_destination_is_rejected(self):
        self.package([('records.csv', b'id\n0001\n')])
        first = self.receive()
        modified = (self.output / 'records.csv').stat().st_mtime_ns
        second = self.receive()
        self.assertEqual(first['archive_sha256'], second['archive_sha256'])
        self.assertEqual(second['status'], 'verified_existing')
        self.assertEqual((self.output / 'records.csv').stat().st_mtime_ns, modified)
        (self.output / 'records.csv').write_bytes(b'id\n0002\n')
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual((self.output / 'records.csv').read_bytes(), b'id\n0002\n')

    def test_partial_or_extra_destination_is_not_repaired_silently(self):
        self.package([('records.csv', b'id\n1\n'), ('other.csv', b'id\n2\n')])
        self.output.mkdir()
        (self.output / 'records.csv').write_bytes(b'id\n1\n')
        with self.assertRaises(ValueError):
            self.receive()
        self.assertFalse((self.output / 'other.csv').exists())
        (self.output / 'other.csv').write_bytes(b'id\n2\n')
        (self.output / 'unexpected.txt').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            self.receive()

    def test_empty_zip_is_rejected(self):
        self.package([])
        self.reject()

    def test_member_count_limit_is_enforced(self):
        self.package([(f'{number}.txt', b'a') for number in range(4097)])
        self.reject()

    def test_archive_member_and_total_size_limits_are_enforced(self):
        self.assertIsNotNone(receiver)
        for limit, maximum in (('MAX_ARCHIVE_BYTES', 20), ('MAX_MEMBER_BYTES', 7), ('MAX_TOTAL_BYTES', 12)):
            with self.subTest(limit=limit):
                self.package([('one.txt', b'12345678'), ('two.txt', b'abcdefgh')])
                with patch.object(receiver, limit, maximum):
                    self.reject()

    def test_cli_refuses_public_extraction_destination(self):
        self.package([('records.csv', b'id\n1\n')])
        script = Path(__file__).with_name('prepare_csv_batch.py')
        command = [sys.executable, str(script), '--archive', str(self.archive),
                   '--output', str(self.output), '--report', str(self.root / 'report.json')]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('beneath this checkout .runtime', result.stderr)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / 'report.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
