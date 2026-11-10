"""Verify a pinned source ZIP and inventory CSVs before private extraction.

Only the Python standard library is used. Cells stay strings and original bytes
are copied unchanged. No importer, database, worker or source generator is run.
The reusable API accepts explicit fixture identities; the CLI keeps the reviewed
GitHub blob and size fixed and writes extracted assets only beneath .runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cb9353499b6ede33fa60b3c67e18a983e362ab16'
SOURCE_BLOB = 'af355c9199304fc7dd37634cdf5d5984feed08be'
SOURCE_BYTES = 2578429
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 500
MAX_BAD_ROW_DETAILS = 200
_ILLEGAL = re.compile(r'[\x00-\x1f<>:"|?*\\]')
_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:[ .]|$)', re.I)


def _member_parts(info):
    name = info.filename
    if (not name or info.orig_filename != name or name.startswith('/')
            or _ILLEGAL.search(name)):
        raise ValueError('Unsafe archive member path')
    path = name[:-1] if info.is_dir() else name
    parts = path.split('/')
    if any(not part or part in ('.', '..') or part.endswith((' ', '.'))
           or _RESERVED.match(part) or len(part.encode('utf-16-le')) > 510 for part in parts):
        raise ValueError('Unsafe or Windows-incompatible archive member path')
    if len(path) > 1024 or PurePosixPath(path).as_posix() != path:
        raise ValueError('Noncanonical archive member path')
    mode = stat.S_IFMT(info.external_attr >> 16)
    if (mode not in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG)
            or info.external_attr & 0x400 or info.flag_bits & (1 | 0x40)):
        raise ValueError('Encrypted, linked or nonregular archive member')
    if info.is_dir() and info.file_size:
        raise ValueError('Archive directory contains unexpected data')
    return tuple(parts)


def _ordinary_path(path):
    """Reject symlink/junction/reparse ancestors before resolving a destination."""
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Extraction destination contains a link or reparse point')


def _csv_summary(content):
    result = {'encoding': None, 'encoding_detection': None, 'header': [],
              'header_valid': False, 'header_issues': [], 'row_count': 0,
              'valid_rows': 0, 'bad_rows': 0, 'blank_rows': 0,
              'bad_row_details': [], 'row_count_complete': True, 'status': 'invalid_csv'}
    if content.startswith((b'\xff\xfe', b'\xfe\xff', b'\x00\x00\xfe\xff')):
        result['header_issues'] = ['unsupported_encoding']
        result['row_count_complete'] = False
        return result
    encoding = 'utf-8-sig' if content.startswith(b'\xef\xbb\xbf') else 'utf-8'
    try:
        value = content.decode(encoding, errors='strict')
        detection = 'strict_utf8_bom' if encoding.endswith('-sig') else 'strict_utf8'
    except UnicodeDecodeError:
        if encoding == 'utf-8-sig':
            # A BOM is an explicit whole-file encoding declaration. Do not
            # reinterpret mixed/invalid UTF-8 as another character encoding.
            result['header_issues'] = ['unsupported_encoding']
            result['row_count_complete'] = False
            return result
        try:
            value = content.decode('gb18030', errors='strict')
            if value.encode('gb18030', errors='strict') != content:
                raise UnicodeError('Noncanonical GB18030 bytes')
            encoding, detection = 'gb18030', 'strict_whole_file_roundtrip_fallback'
        except UnicodeError:
            result['header_issues'] = ['unsupported_encoding']
            result['row_count_complete'] = False
            return result
    result.update(encoding=encoding, encoding_detection=detection)
    if '\x00' in value:
        result['header_issues'] = ['nul_in_csv']
        result['row_count_complete'] = False
        return result
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_MEMBER_BYTES)
    try:
        reader = csv.reader(io.StringIO(value, newline=''), strict=True)
        try:
            header = next(reader)
        except StopIteration:
            result['header_issues'] = ['missing_header']
            return result
        except csv.Error:
            result['header_issues'] = ['csv_parse_error']
            result['row_count_complete'] = False
            return result
        issues = []
        if not header:
            issues.append('missing_header')
            result['blank_rows'] += 1
        if any(not cell.strip() for cell in header):
            issues.append('empty_header')
        if len(set(header)) != len(header):
            issues.append('duplicate_header')
        result.update(header=header, header_valid=not issues, header_issues=issues)
        record_number = 1
        while True:
            start = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error:
                result['bad_rows'] += 1
                result['row_count_complete'] = False
                if len(result['bad_row_details']) < MAX_BAD_ROW_DETAILS:
                    result['bad_row_details'].append({'code': 'csv_parse_error',
                        'record_number': record_number + 1, 'line_start': start, 'line_end': reader.line_num})
                break  # A malformed quoted record has no provably safe next row boundary.
            record_number += 1
            if not row:
                result['blank_rows'] += 1
                continue
            result['row_count'] += 1
            if len(row) == len(header):
                result['valid_rows'] += 1
            else:
                result['bad_rows'] += 1
                if len(result['bad_row_details']) < MAX_BAD_ROW_DETAILS:
                    result['bad_row_details'].append({'code': 'column_count_mismatch',
                        'record_number': record_number, 'line_start': start, 'line_end': reader.line_num,
                        'expected_columns': len(header), 'actual_columns': len(row)})
        result['bad_row_details_truncated'] = result['bad_rows'] > len(result['bad_row_details'])
        if result['header_valid'] and result['bad_rows'] == 0:
            result['status'] = 'valid_csv'
        return result
    finally:
        csv.field_size_limit(previous_limit)


def _existing_output(output, files, directories):
    """Compare the entire existing extraction before making any writes."""
    _ordinary_path(output)
    if not output.exists():
        return False
    if not output.is_dir():
        raise ValueError('Extraction destination is not a directory')
    actual = {}
    for path in output.rglob('*'):
        _ordinary_path(path)
        relative = path.relative_to(output).as_posix()
        if path.is_dir():
            if relative not in directories:
                raise ValueError('Existing extraction directory inventory differs')
        elif path.is_file():
            actual[relative] = path
        else:
            raise ValueError('Existing extraction contains a nonregular entry')
    if not actual and not any(output.iterdir()):
        return False
    if actual.keys() != files.keys():
        raise ValueError('Existing extraction file inventory differs; refusing repair')
    for name, path in actual.items():
        expected = files[name]
        if path.stat().st_size != expected['bytes']:
            raise ValueError('Existing extraction bytes differ; refusing overwrite')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected['sha256']:
            raise ValueError('Existing extraction bytes differ; refusing overwrite')
    return True


def prepare(archive: Path, output: Path, expected_blob=SOURCE_BLOB, expected_size=SOURCE_BYTES):
    """Return a row-free inventory after full ZIP validation and safe extraction.

    ``row_count`` counts parsed nonblank data records, including width errors.
    ``valid_rows`` counts width-correct data records; header validity is separate.
    A lexical CSV failure sets ``row_count_complete=False`` instead of guessing
    the next record boundary. Invalid CSVs remain unchanged source evidence.
    """
    archive, output = Path(archive).absolute(), Path(output).absolute()
    size = archive.stat().st_size
    if size > MAX_ARCHIVE_BYTES or expected_size is not None and size != expected_size:
        raise ValueError('Archive size differs from reviewed source or exceeds limit')
    data = archive.read_bytes()
    if len(data) != size:
        raise ValueError('Archive changed while being read')
    blob = hashlib.sha1(b'blob ' + str(size).encode('ascii') + b'\0' + data).hexdigest()
    if expected_blob is not None and blob != expected_blob:
        raise ValueError('Archive Git blob differs from reviewed source')
    files, directories, spelling, inventory = {}, set(), {}, []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            infos = package.infolist()
            if not infos or len(infos) > MAX_MEMBERS:
                raise ValueError('Archive member count outside allowed bounds')
            total = 0
            explicit = set()
            for info in infos:
                parts = _member_parts(info)
                name = '/'.join(parts)
                if name.casefold() in explicit:
                    raise ValueError('Duplicate or case-colliding archive member')
                explicit.add(name.casefold())
                # Include implied parent directories in case-collision checks.
                for length in range(1, len(parts) + 1):
                    prefix = '/'.join(parts[:length])
                    old = spelling.setdefault(prefix.casefold(), prefix)
                    if old != prefix:
                        raise ValueError('Case-colliding archive directory spelling')
                if info.file_size > MAX_MEMBER_BYTES or info.file_size < 0 or info.compress_size < 0:
                    raise ValueError('Archive member size outside allowed bounds')
                if info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
                    raise ValueError('Archive compression ratio exceeds limit')
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ValueError('Archive total uncompressed size exceeds limit')
                directories.update('/'.join(parts[:length]) for length in range(1, len(parts)))
                if info.is_dir():
                    directories.add(name)
                else:
                    files[name] = info
            if not files:
                raise ValueError('Archive has no source files')
            if files.keys() & directories:
                raise ValueError('Archive file/directory identity conflict')
            metadata = {}
            # ZipFile.read verifies CRC. The immutable byte snapshot prevents
            # a changed source archive from being substituted between passes.
            for name, info in files.items():
                content = package.read(info)
                if len(content) != info.file_size:
                    raise ValueError('Archive member uncompressed size mismatch')
                parts = PurePosixPath(name).parts
                is_metadata = (any(part.casefold() == '__macosx' for part in parts)
                               or parts[-1].startswith('._'))
                is_csv = not is_metadata and PurePosixPath(name).suffix.casefold() == '.csv'
                item = {'path': name, 'bytes': len(content),
                        'sha256': hashlib.sha256(content).hexdigest(),
                        'compressed_bytes': info.compress_size, 'crc32': f'{info.CRC:08x}',
                        'member_role': 'metadata' if is_metadata else 'csv' if is_csv else 'other',
                        'is_csv': is_csv}
                if item['is_csv']:
                    item.update(_csv_summary(content))
                metadata[name] = item
                inventory.append(item)
            # Even an empty directory entry must pass decompression/CRC.
            for info in infos:
                if info.is_dir():
                    package.read(info)
            reused = _existing_output(output, metadata, directories)
            if not reused:
                # This is the first filesystem mutation, after all preflight.
                output.mkdir(parents=True, exist_ok=True)
                _ordinary_path(output)
                for name in sorted(directories, key=lambda item: (item.count('/'), item)):
                    path = output.joinpath(*PurePosixPath(name).parts)
                    _ordinary_path(path)
                    path.mkdir(exist_ok=True)
                for name, info in files.items():
                    path = output.joinpath(*PurePosixPath(name).parts)
                    _ordinary_path(path)
                    if not path.resolve().is_relative_to(output.resolve()):
                        raise ValueError('Extraction destination escapes output')
                    with path.open('xb') as stream:
                        stream.write(package.read(info))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError('ZIP integrity or supported-format validation failed') from error
    csv_files = [item for item in inventory if item['is_csv']]
    pinned = blob == SOURCE_BLOB and size == SOURCE_BYTES
    return {'contract': 'csv-batch-source/1', 'status': 'verified_existing' if reused else 'prepared',
            'source_repository': 'lianggeming14/upload-files' if pinned else None,
            'source_commit': SOURCE_COMMIT if pinned else None, 'source_archive_path': 'csv.zip' if pinned else None,
            'archive_git_blob': blob, 'archive_sha256': hashlib.sha256(data).hexdigest(), 'archive_bytes': size,
            'member_count': len(infos), 'file_count': len(files), 'csv_file_count': len(csv_files),
            'metadata_file_count': sum(item['member_role'] == 'metadata' for item in inventory),
            'total_uncompressed_bytes': total, 'members': inventory,
            'csv_status': 'passed' if csv_files and all(item['status'] == 'valid_csv' for item in csv_files) else 'needs_review',
            'row_count': sum(item['row_count'] for item in csv_files),
            'bad_rows': sum(item['bad_rows'] for item in csv_files),
            'blank_rows': sum(item['blank_rows'] for item in csv_files),
            'encodings': dict(Counter(item['encoding'] or 'unrecognized' for item in csv_files)),
            'raw_rows_published': False, 'database_accessed': False, 'generator_executed': False,
            'formal_adoption': False,
            'encoding_policy': 'Whole-file strict UTF-8 first; strict GB18030 roundtrip fallback; never per-cell decoding',
            'limits': {'archive_bytes': MAX_ARCHIVE_BYTES, 'members': MAX_MEMBERS,
                'member_bytes': MAX_MEMBER_BYTES, 'total_bytes': MAX_TOTAL_BYTES,
                'compression_ratio': MAX_COMPRESSION_RATIO, 'bad_row_details_per_file': MAX_BAD_ROW_DETAILS}}


def _write_report(report, manifest):
    """Refresh derived inventory only when the original source identities match."""
    report = Path(report).absolute()
    _ordinary_path(report)
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if report.exists():
        previous = json.loads(report.read_text(encoding='utf-8-sig'))
        if previous == manifest:
            return
        identity = ('contract', 'archive_git_blob', 'archive_sha256', 'archive_bytes')
        try:
            same_archive = all(previous[key] == manifest[key] for key in identity)
            previous_files = sorted((item['path'], item['bytes'], item['sha256']) for item in previous['members'])
            current_files = sorted((item['path'], item['bytes'], item['sha256']) for item in manifest['members'])
        except (KeyError, TypeError):
            raise ValueError('Existing report is not a source inventory; refusing overwrite') from None
        if not same_archive or previous_files != current_files:
            raise ValueError('Existing report source bytes differ; refusing overwrite')
    report.parent.mkdir(parents=True, exist_ok=True)
    stage = None
    try:
        with tempfile.NamedTemporaryFile(dir=report.parent, prefix='.' + report.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            stage = Path(stream.name)
            stream.write(encoded)
        stage.replace(report)
    finally:
        if stage is not None and stage.exists():
            stage.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True, help='Row-free JSON inventory suitable for review')
    args = parser.parse_args(argv)
    if not args.output.resolve().is_relative_to((ROOT / '.runtime').resolve()):
        parser.error('Source extraction output must stay beneath this checkout .runtime')
    _ordinary_path(args.output.absolute())
    report = args.report.absolute()
    _ordinary_path(report)
    if report.resolve().is_relative_to(args.output.resolve()) or report.resolve() == args.archive.resolve():
        raise ValueError('Report must be separate from original archive and extraction inventory')
    manifest = prepare(args.archive, args.output)
    _write_report(report, manifest)
    print(json.dumps({key: value for key, value in manifest.items() if key != 'members'}, ensure_ascii=True, indent=2))
    return 0 if manifest['csv_status'] == 'passed' else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit('CSV source preparation failed: ' + str(error)) from None
