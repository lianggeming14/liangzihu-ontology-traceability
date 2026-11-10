"""Plan, explicitly apply, or read-only verify the isolated reviewed CSV schema.

The default mode verifies source bytes and writes only row-free SQL/structure
artifacts. --apply is required for database creation; --verify cannot create or
repair a schema. This command does not import the formal platform or use Jena.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from csv_batch_model import read_tables, build_snapshot
from csv_batch_store import (PACKAGE, SCHEMA, ReadbackError, guard_target, structure,
                             store_snapshot, validate_snapshot)
from prepare_csv_batch import prepare

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.runtime/source-imports/csv-2026-11-09/cb9353499b6e'
OUTPUT = ROOT / 'docs/csv-batch'


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def failure_report(error):
    report = dict(error.report) if isinstance(error, ReadbackError) else {
        'contract': 'csv-batch-pg-readback/1', 'schema': SCHEMA, 'package_sha256': PACKAGE}
    report.update(status='failed', exception_type=type(error).__name__, operation_completed=False,
                  transaction_committed=False, formal_adoption=False, raw_payload_public=False,
                  error='CSV PostgreSQL operation did not complete')
    return report


def load_source():
    manifest_path = OUTPUT / 'source-manifest.json'
    published = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    extracted = SOURCE / 'extracted'
    if not extracted.is_dir():
        raise ValueError('Verified extraction is absent; prepare it explicitly first')
    manifest = prepare(SOURCE / 'source.zip', extracted)
    keys = ('archive_sha256', 'archive_git_blob', 'archive_bytes', 'csv_file_count', 'row_count', 'csv_status')
    if any(published.get(key) != manifest[key] for key in keys) or manifest['archive_sha256'] != PACKAGE:
        raise ValueError('Published source inventory differs from verified source bytes')
    original_files = sorted((item['path'], item['bytes'], item['sha256']) for item in published['members'])
    verified_files = sorted((item['path'], item['bytes'], item['sha256']) for item in manifest['members'])
    if original_files != verified_files or manifest['csv_status'] != 'passed':
        raise ValueError('Source member inventory is incomplete or invalid')
    tables, metadata = read_tables(extracted, manifest)
    definitions = json.loads((ROOT / 'datasets/fish/source-schema.json').read_text(encoding='utf-8'))
    rules = json.loads((OUTPUT / 'relation-map.json').read_text(encoding='utf-8'))['relations']
    snapshot, model_report = build_snapshot(tables, definitions, rules, PACKAGE, metadata=metadata)
    if any(model_report[key] for key in ('duplicate_rows', 'conflicting_rows', 'quarantined_rows', 'invalid_typed_cells')):
        raise ValueError('The reviewed batch must have no unusable source identities or typed cells')
    validate_snapshot(snapshot, require_full_batch=True)
    emit({'stage': 'source_verified', 'source_tables': model_report['source_tables'],
          'raw_rows': model_report['raw_rows'], 'instances': model_report['instances'],
          'relations': model_report['relations'], 'resolved_relations': model_report['resolved_relations']})
    return snapshot, rules


def export_structure(plan):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sql = '-- Isolated CSV batch only; requires an absent schema. No original record values.\n'
    sql += '\n\n'.join(statement + ';' for statement in plan['statements']) + '\n'
    (OUTPUT / 'schema.sql').write_text(sql, encoding='utf-8')
    (OUTPUT / 'schema-structure.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def connect_private(config_path):
    # The existing guard reads APP_ENV=test and the explicit private dotenv file.
    # Credentials are never placed in argv, reports, exceptions or child envs.
    from fish_review_config import database_url, load_config
    from sqlalchemy.engine import make_url
    import psycopg
    config = load_config(config_path)
    raw = database_url(config)
    guard_target(raw, SCHEMA, PACKAGE)
    parsed = make_url(raw)
    try:
        return psycopg.connect(host='127.0.0.1', port=25449, dbname='lzo_gis', user='lzo_gis_owner',
                               password=parsed.password, connect_timeout=10,
                               application_name='csv-batch-isolated-review', autocommit=True)
    except Exception as error:
        raise ValueError('Reviewed PostgreSQL connection failed (' + type(error).__name__ + ')') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true', help='Explicitly create only the absent pinned schema')
    modes.add_argument('--verify', action='store_true', help='Read-only complete verification; never create or repair')
    parser.add_argument('--config', type=Path, default=ROOT / 'config/fish-review.example.json',
                        help='Existing nonsecret local review configuration')
    args = parser.parse_args(argv)
    started = time.monotonic()
    snapshot, rules = load_source()
    plan = structure(snapshot, rules)
    export_structure(plan)
    if not args.apply and not args.verify:
        emit({'stage': 'planned_not_applied', 'schema': SCHEMA, 'database_accessed': False,
              'business_tables': plan['business_tables'], 'support_tables': plan['support_tables'],
              'field_dictionary_entries': plan['field_dictionary_entries'],
              'confirmed_scalar_foreign_keys': plan['confirmed_scalar_foreign_keys']})
        return 0
    connection = connect_private(args.config)
    try:
        report = store_snapshot(connection, snapshot, rules, apply=args.apply, progress=emit)
    except ReadbackError as error:
        report = {**error.report, 'transaction_committed': False, 'new_schema_rolled_back': True}
        (OUTPUT / 'pg-readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    finally:
        connection.close()
    report['seconds'] = round(time.monotonic() - started, 3)
    (OUTPUT / 'pg-readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    emit({key: report[key] for key in ('status', 'schema', 'schema_created', 'existing_schema_verified',
          'raw_rows_checked', 'original_cells_checked', 'business_cells_checked', 'nodes_checked',
          'relations_checked', 'resolved_relations', 'unresolved_relations', 'seconds')})
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Native driver messages can include source cells. Public failure output
        # records the class only; a failed or incomplete read is never "passed".
        report = failure_report(error)
        try:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            (OUTPUT / 'pg-readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except OSError:
            report['failure_report_written'] = False
        emit(report)
        raise SystemExit(1) from None
