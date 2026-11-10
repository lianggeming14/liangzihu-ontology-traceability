"""Create-only PostgreSQL storage and complete readback for one reviewed CSV batch.

No SQL is issued at import time. Native psycopg COPY is used only by the explicit
store entry point. Existing schemas are verified in place and never repaired.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from itertools import zip_longest
import json
import re
from urllib.parse import unquote, urlsplit
from uuid import UUID

PACKAGE = 'a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524'
SCHEMA = 'csv_batch_a4d78be79a83'
FULL_COUNTS = (66, 153862, 153862, 810934)
ADOPTION = 'csv_batch_received_not_formally_adopted'
_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]*\Z')


def guard_target(database_url, schema=SCHEMA, package_sha256=PACKAGE):
    try:
        value = urlsplit(database_url)
        valid = (value.scheme == 'postgresql+psycopg' and value.hostname == '127.0.0.1'
                 and value.port == 25449 and value.path == '/lzo_gis'
                 and unquote(value.username or '') == 'lzo_gis_owner'
                 and bool(value.password) and not value.query and not value.fragment
                 and schema == SCHEMA and package_sha256 == PACKAGE)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Only the reviewed loopback GIS owner, database, port, package and new schema are allowed')


def guard_server(target):
    # inet::text can include PostgreSQL's explicit single-host /32 mask.
    if (not isinstance(target, tuple) or len(target) != 4
            or target[:2] != ('lzo_gis', 'lzo_gis_owner') or target[3] != 25449
            or target[2] not in ('127.0.0.1', '127.0.0.1/32')):
        raise ValueError('Actual PostgreSQL server identity differs from reviewed target')


def quoted(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) or len(value.encode()) > 63:
        raise ValueError('Unsafe PostgreSQL identifier')
    return '"' + value + '"'


def qualified(name):
    return quoted(SCHEMA) + '.' + quoted(name)


def sql_type(definition):
    if definition.get('format') == 'date-time':
        return 'TIMESTAMP WITH TIME ZONE'
    if definition.get('format') == 'date':
        return 'DATE'
    kind = definition.get('type', 'string')
    if isinstance(kind, list):
        kind = next((item for item in kind if item != 'null'), 'string')
    if kind in ('number', 'integer'):
        return 'NUMERIC'
    if kind == 'boolean':
        return 'BOOLEAN'
    if kind != 'string':
        raise ValueError('Unsupported source column type')
    return 'TEXT'


def typed_value(value, definition):
    if value is None:
        return None
    target = sql_type(definition)
    if target == 'NUMERIC':
        if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
            raise ValueError('Numeric source must be exact decimal text or integer')
        try:
            result = Decimal(value)
        except (InvalidOperation, ValueError):
            raise ValueError('Invalid numeric source') from None
        kind = definition.get('type', 'string')
        if not result.is_finite() or ('integer' in kind and result != result.to_integral_value()):
            raise ValueError('Non-finite or non-integral source numeric')
        return result
    if target == 'BOOLEAN':
        if type(value) is not bool:
            raise ValueError('Boolean source must already be explicitly normalized')
        return value
    if not isinstance(value, str):
        raise ValueError('Text and temporal source values must remain text')
    if target == 'TIMESTAMP WITH TIME ZONE':
        fractional = re.search(r'T\d{2}:\d{2}:\d{2}[.,](\d+)', value)
        if fractional and len(fractional[1].rstrip('0')) > 6:
            raise ValueError('Source timestamp exceeds exact PostgreSQL microsecond precision')
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('Invalid source timestamp') from None
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError('Source timestamp requires an explicit timezone')
        return result.astimezone(timezone.utc)
    if target == 'DATE':
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError('Invalid source date') from None
    return value


def _json_default(value):
    if isinstance(value, Decimal):
        lexical = format(value, 'f')
        if '.' in lexical:
            lexical = lexical.rstrip('0').rstrip('.')
        return {'decimal': '0' if value == 0 else lexical}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError('Readback returned a naive timestamp')
        return {'timestamptz': value.astimezone(timezone.utc).isoformat(timespec='microseconds')}
    if isinstance(value, date):
        return {'date': value.isoformat()}
    if isinstance(value, UUID):
        return str(value)
    raise TypeError('Unsupported value in deterministic readback')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      default=_json_default).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def validate_snapshot(snapshot, *, require_full_batch=False):
    if snapshot.get('package_sha256') != PACKAGE or snapshot.get('source_schema') != SCHEMA:
        raise ValueError('Snapshot belongs to another batch or schema')
    tables = snapshot['schema']['tables']
    for table, spec in tables.items():
        quoted('data_' + table)
        if spec.get('primary_key') != ['id'] or sql_type(spec['columns'].get('id', {})) != 'TEXT':
            raise ValueError('Business tables must retain their text id primary key')
        for field in spec['columns']:
            quoted(field)
    raw = {}
    for row in snapshot['raw']:
        key = row['table_name'], row['row_number']
        if key in raw or key[0] not in tables or type(key[1]) is not int or key[1] < 1:
            raise ValueError('Duplicate or invalid physical source identity')
        if set(row['payload']) != set(tables[key[0]]['columns']) or any(type(cell) is not str for cell in row['payload'].values()):
            raise ValueError('Raw source fields or original cell types differ')
        raw[key] = row
    nodes, sources = {}, set()
    for node in snapshot['nodes']:
        identifier = str(UUID(node['node_id']))
        key = node['table_name'], node['source_row']
        source = raw.get(key)
        if (identifier in nodes or (node['table_name'], node['source_pk']) in sources or source is None
                or source['source_pk'] != node['source_pk'] or source['status'] not in ('accepted', 'needs_review')):
            raise ValueError('Canonical node has no exact usable physical source')
        if set(node['properties']) != set(tables[node['table_name']]['columns']):
            raise ValueError('Node properties differ from its field dictionary')
        for field, definition in tables[node['table_name']]['columns'].items():
            typed_value(node['properties'][field], definition)
        nodes[identifier] = node
        sources.add((node['table_name'], node['source_pk']))
    edge_ids = set()
    for edge in snapshot['relations']:
        source = nodes.get(edge['from_node'])
        target = nodes.get(edge['to_node']) if edge['to_node'] is not None else None
        if edge['edge_id'] in edge_ids or source is None or source['source_row'] != edge['source_row']:
            raise ValueError('Relationship source identity differs')
        edge_ids.add(edge['edge_id'])
        if edge['resolution'] == 'resolved':
            if target is None or (target['table_name'], target['source_pk']) != (edge['target_table'], edge['target_pk']):
                raise ValueError('Resolved relationship target differs')
        elif edge['to_node'] is not None:
            raise ValueError('Unresolved relationship must retain a NULL target')
    if require_full_batch and (len(tables), len(raw), len(nodes), len(edge_ids)) != FULL_COUNTS:
        raise ValueError('The reviewed complete batch counts are required before database access')
    return nodes


def identity(snapshot, rules):
    stream = hashlib.sha256()
    for key in ('raw', 'nodes', 'relations'):
        stream.update(key.encode() + b'\n')
        for row in snapshot[key]:
            stream.update(encoded(row) + b'\n')
    return {'contract': 'csv-batch-postgres/1', 'schema': SCHEMA, 'package_sha256': PACKAGE,
            'logical_schema_sha256': digest(snapshot['schema']), 'relation_rules_sha256': digest(rules),
            'snapshot_sha256': stream.hexdigest(), 'business_tables': len(snapshot['schema']['tables']),
            'raw_records': len(snapshot['raw']), 'ontology_nodes': len(snapshot['nodes']),
            'ontology_relations': len(snapshot['relations']), 'complete': True, 'formal_adoption': False}


def assert_identity(actual, expected):
    if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError('Existing batch source, schema, rules, completion or content identity differs; refusing overwrite')
    if not re.fullmatch(r'[0-9a-f]{64}', actual.get('physical_schema_sha256', '')):
        raise ValueError('Existing batch has no complete physical-schema identity')


def structure(snapshot, rules):
    validate_snapshot(snapshot)
    statements = ['CREATE SCHEMA ' + quoted(SCHEMA)]
    tables = []

    def add(name, columns, constraints=()):
        clauses = [quoted(field) + ' ' + kind + (' ' + options if options else '') for field, kind, options in columns]
        clauses.extend(constraints)
        statements.append('CREATE TABLE ' + qualified(name) + ' (\n  ' + ',\n  '.join(clauses) + '\n)')
        tables.append({'name': name, 'columns': [{'name': field, 'sql_type': kind, 'options': options}
                                              for field, kind, options in columns]})

    add('batch_metadata', [('id', 'TEXT', 'PRIMARY KEY'), ('document', 'JSONB', 'NOT NULL')],
        ['CHECK ("id" = \'batch\')'])
    add('source_tables', [('table_name', 'TEXT', 'PRIMARY KEY'), ('source_path', 'TEXT', 'NOT NULL'),
                         ('definition', 'JSONB', 'NOT NULL')])
    add('field_dictionary', [('table_name', 'TEXT', 'NOT NULL'), ('field_name', 'TEXT', 'NOT NULL'),
                            ('ordinal', 'INTEGER', 'NOT NULL'), ('definition', 'JSONB', 'NOT NULL'),
                            ('column_sql_type', 'TEXT', 'NOT NULL')],
        ['PRIMARY KEY ("table_name", "field_name")',
         'FOREIGN KEY ("table_name") REFERENCES ' + qualified('source_tables') + ' ("table_name")'])
    add('raw_records', [('table_name', 'TEXT', 'NOT NULL'), ('row_number', 'BIGINT', 'NOT NULL'),
        ('source_pk', 'TEXT', 'NOT NULL'), ('payload', 'JSONB', 'NOT NULL'), ('status', 'TEXT', 'NOT NULL'),
        ('issues', 'JSONB', 'NOT NULL'), ('sample_reason', 'TEXT', 'NOT NULL'), ('package_sha256', 'TEXT', 'NOT NULL')],
        ['PRIMARY KEY ("table_name", "row_number")', 'CHECK ("row_number" > 0)',
         'FOREIGN KEY ("table_name") REFERENCES ' + qualified('source_tables') + ' ("table_name")'])
    add('ontology_nodes', [('node_id', 'UUID', 'PRIMARY KEY'), ('table_name', 'TEXT', 'NOT NULL'),
        ('source_pk', 'TEXT', 'NOT NULL'), ('source_row', 'BIGINT', 'NOT NULL'), ('properties', 'JSONB', 'NOT NULL'),
        ('nature', 'TEXT', 'NOT NULL'), ('role', 'TEXT', 'NOT NULL'), ('adoption_status', 'TEXT', 'NOT NULL')],
        ['UNIQUE ("table_name", "source_pk")', 'UNIQUE ("node_id", "table_name", "source_row")',
         'UNIQUE ("node_id", "table_name", "source_pk")',
         'FOREIGN KEY ("table_name", "source_row") REFERENCES ' + qualified('raw_records') + ' ("table_name", "row_number")'])
    add('ontology_relations', [('edge_id', 'BIGINT', 'PRIMARY KEY'), ('from_node', 'UUID', 'NOT NULL'),
        ('from_table', 'TEXT', 'NOT NULL'), ('field_name', 'TEXT', 'NOT NULL'), ('target_table', 'TEXT', 'NOT NULL'),
        ('target_pk', 'TEXT', 'NOT NULL'), ('to_node', 'UUID', ''), ('resolution', 'TEXT', 'NOT NULL'),
        ('source_row', 'BIGINT', 'NOT NULL'), ('list_index', 'BIGINT', ''), ('evidence', 'TEXT', 'NOT NULL')],
        ['FOREIGN KEY ("from_node", "from_table", "source_row") REFERENCES ' + qualified('ontology_nodes') + ' ("node_id", "table_name", "source_row")',
         'FOREIGN KEY ("to_node", "target_table", "target_pk") REFERENCES ' + qualified('ontology_nodes') + ' ("node_id", "table_name", "source_pk")',
         'FOREIGN KEY ("from_table", "source_row") REFERENCES ' + qualified('raw_records') + ' ("table_name", "row_number")',
         'CHECK (("resolution" = \'resolved\' AND "to_node" IS NOT NULL) OR ("resolution" <> \'resolved\' AND "to_node" IS NULL))'])
    for table, spec in sorted(snapshot['schema']['tables'].items()):
        columns = [(field, sql_type(definition), 'PRIMARY KEY' if field == 'id' else '')
                   for field, definition in spec['columns'].items()]
        columns += [('_node_id', 'UUID', 'NOT NULL UNIQUE'), ('_source_row', 'BIGINT', 'NOT NULL'),
                    ('_data_nature', 'TEXT', 'NOT NULL'), ('_source_table', 'TEXT', "NOT NULL DEFAULT '" + table + "'")]
        # Underscore metadata columns are fixed names; source headers cannot use them.
        clauses = []
        for field, kind, options in columns:
            if field.startswith('_'):
                clauses.append('"' + field + '" ' + kind + ' ' + options)
            else:
                clauses.append(quoted(field) + ' ' + kind + (' ' + options if options else ''))
        clauses += ['FOREIGN KEY ("_node_id") REFERENCES ' + qualified('ontology_nodes') + ' ("node_id")',
                    'FOREIGN KEY ("_source_table", "_source_row") REFERENCES ' + qualified('raw_records') + ' ("table_name", "row_number")',
                    'CHECK ("_source_table" = \'' + table + '\')']
        statements.append('CREATE TABLE ' + qualified('data_' + table) + ' (\n  ' + ',\n  '.join(clauses) + '\n)')
        tables.append({'name': 'data_' + table, 'source_table': table,
                       'columns': [{'name': field, 'sql_type': kind, 'options': options} for field, kind, options in columns]})
    scalar = set()
    for rule in rules:
        if rule.get('kind') != 'scalar' or rule.get('missing_target_count') != 0:
            continue
        source, field, target = rule['source_table'], rule['field'], rule['target_table']
        if rule.get('target_field', 'id') != 'id' or target not in snapshot['schema']['tables']:
            continue
        key = source, field, target
        if key in scalar:
            continue
        scalar.add(key)
        if sql_type(snapshot['schema']['tables'][source]['columns'][field]) != 'TEXT':
            raise ValueError('Confirmed scalar identifier must retain its source text type')
        constraint = 'csv_fk_' + digest(key)[:20]
        statements.append('ALTER TABLE ' + qualified('data_' + source) + ' ADD CONSTRAINT ' + quoted(constraint)
            + ' FOREIGN KEY (' + quoted(field) + ') REFERENCES ' + qualified('data_' + target)
            + ' ("id") DEFERRABLE INITIALLY DEFERRED')
    statements += ['CREATE INDEX csv_rel_from ON ' + qualified('ontology_relations') + ' ("from_node")',
                   'CREATE INDEX csv_rel_to ON ' + qualified('ontology_relations') + ' ("to_node")']
    return {'contract': 'csv-batch-postgres-structure/1', 'schema': SCHEMA, 'package_sha256': PACKAGE,
            'business_tables': len(snapshot['schema']['tables']), 'support_tables': 6,
            'field_dictionary_entries': sum(len(spec['columns']) for spec in snapshot['schema']['tables'].values()),
            'confirmed_scalar_foreign_keys': len(scalar), 'tables': tables, 'statements': statements,
            'formal_adoption': False, 'raw_records_in_export': False}


def compare_rows(expected, actual, label):
    sentinel = object()
    expected_hash, actual_hash = hashlib.sha256(), hashlib.sha256()
    expected_count = actual_count = mismatches = checked = 0
    locations = []
    for checked, (left, right) in enumerate(zip_longest(expected, actual, fillvalue=sentinel), 1):
        left_bytes = right_bytes = None
        if left is not sentinel:
            expected_count += 1
            left_bytes = encoded(left)
            expected_hash.update(left_bytes + b'\n')
        if right is not sentinel:
            actual_count += 1
            right_bytes = encoded(right)
            actual_hash.update(right_bytes + b'\n')
        if left_bytes != right_bytes:
            mismatches += 1
            if len(locations) < 20:
                locations.append(checked)
    return {'label': label, 'status': 'passed' if mismatches == 0 else 'failed', 'rows_checked': checked,
            'expected_rows': expected_count, 'actual_rows': actual_count, 'mismatch_rows': mismatches,
            'mismatch_ordinals': locations, 'expected_sha256': expected_hash.hexdigest(),
            'actual_sha256': actual_hash.hexdigest()}


def _physical(connection):
    columns = connection.execute('''SELECT c.relname,a.attnum,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),
        a.attnotnull,COALESCE(pg_catalog.pg_get_expr(d.adbin,d.adrelid),'') FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname=%s AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname COLLATE "C",a.attnum''', (SCHEMA,)).fetchall()
    constraints = connection.execute('''SELECT c.relname,k.conname,k.contype,pg_catalog.pg_get_constraintdef(k.oid)
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s
        ORDER BY c.relname COLLATE "C",k.conname COLLATE "C"''', (SCHEMA,)).fetchall()
    indexes = connection.execute('''SELECT tablename,indexname,indexdef FROM pg_catalog.pg_indexes
        WHERE schemaname=%s ORDER BY tablename COLLATE "C",indexname COLLATE "C"''', (SCHEMA,)).fetchall()
    return digest({'columns': columns, 'constraints': constraints, 'indexes': indexes}), columns


def _rows(snapshot):
    nodes = {row['node_id']: row for row in snapshot['nodes']}
    specs = snapshot['schema']['tables']
    yield 'source_tables', ['table_name', 'source_path', 'definition'], (
        (table, spec['path'], spec) for table, spec in sorted(specs.items()))
    yield 'field_dictionary', ['table_name', 'field_name', 'ordinal', 'definition', 'column_sql_type'], (
        (table, field, ordinal, definition, sql_type(definition)) for table, spec in sorted(specs.items())
        for ordinal, (field, definition) in enumerate(spec['columns'].items(), 1))
    yield 'raw_records', ['table_name', 'row_number', 'source_pk', 'payload', 'status', 'issues', 'sample_reason', 'package_sha256'], (
        (row['table_name'], row['row_number'], row['source_pk'], row['payload'], row['status'], row['issues'],
         row['sample_reason'], PACKAGE) for row in sorted(snapshot['raw'], key=lambda row: (row['table_name'], row['row_number'])))
    yield 'ontology_nodes', ['node_id', 'table_name', 'source_pk', 'source_row', 'properties', 'nature', 'role', 'adoption_status'], (
        (row['node_id'], row['table_name'], row['source_pk'], row['source_row'], row['properties'], row['nature'], row['role'], ADOPTION)
        for row in sorted(snapshot['nodes'], key=lambda row: row['node_id']))
    relation_columns = ['edge_id', 'from_node', 'from_table', 'field_name', 'target_table', 'target_pk', 'to_node', 'resolution',
                        'source_row', 'list_index', 'evidence']
    yield 'ontology_relations', relation_columns, (
        (row['edge_id'], row['from_node'], nodes[row['from_node']]['table_name'], row['field_name'], row['target_table'],
         row['target_pk'], row['to_node'], row['resolution'], row['source_row'], row.get('list_index'), row['evidence'])
        for row in sorted(snapshot['relations'], key=lambda row: row['edge_id']))
    grouped = defaultdict(list)
    for node in snapshot['nodes']:
        grouped[node['table_name']].append(node)
    for table, spec in sorted(specs.items()):
        fields = list(spec['columns'])
        def values(table=table, spec=spec, fields=fields):
            for node in sorted(grouped[table], key=lambda node: node['source_pk']):
                yield tuple(typed_value(node['properties'][field], spec['columns'][field]) for field in fields) + (
                    node['node_id'], node['source_row'], node['nature'], table)
        yield 'data_' + table, fields + ['_node_id', '_source_row', '_data_nature', '_source_table'], values()


def _column_sql(columns):
    # Fixed underscore metadata names cannot be passed in by source headers.
    return ','.join('"' + name + '"' if name in ('_node_id', '_source_row', '_data_nature', '_source_table')
                    else quoted(name) for name in columns)


def verify(connection, snapshot, rules, *, plan=None):
    plan = structure(snapshot, rules) if plan is None else plan
    expected_identity = identity(snapshot, rules)
    stored = connection.execute('SELECT document FROM ' + qualified('batch_metadata') + ' WHERE id=%s', ('batch',)).fetchall()
    if len(stored) != 1:
        raise ValueError('Existing schema has no unique completed batch identity')
    document = stored[0][0]
    assert_identity(document, expected_identity)
    physical, columns = _physical(connection)
    planned = {(table['name'], column['name']): column['sql_type'].lower() for table in plan['tables'] for column in table['columns']}
    actual = {(row[0], row[2]): row[3] for row in columns}
    shape_ok = actual == planned and physical == document['physical_schema_sha256']
    checks = []
    ordering = {'source_tables': '"table_name" COLLATE "C"',
                'field_dictionary': '"table_name" COLLATE "C","ordinal"',
                'raw_records': '"table_name" COLLATE "C","row_number"',
                'ontology_nodes': '"node_id"', 'ontology_relations': '"edge_id"'}
    for number, (table, field_names, expected) in enumerate(_rows(snapshot)):
        order = ordering.get(table, '"id" COLLATE "C"')
        with connection.cursor(name='csv_batch_read_' + str(number)) as cursor:
            cursor.itersize = 2000
            cursor.execute('SELECT ' + _column_sql(field_names) + ' FROM ' + qualified(table) + ' ORDER BY ' + order)
            checks.append(compare_rows(expected, cursor, table))
    metadata_rows = connection.execute('SELECT id,document FROM ' + qualified('batch_metadata') + ' ORDER BY id').fetchall()
    checks.append(compare_rows([('batch', document)], metadata_rows, 'batch_metadata'))
    status = 'passed' if shape_ok and all(check['status'] == 'passed' for check in checks) else 'failed'
    return {'contract': 'csv-batch-pg-readback/1', 'status': status, 'schema': SCHEMA, 'package_sha256': PACKAGE,
            'database': 'lzo_gis', 'physical_schema_sha256': physical, 'schema_structure_matches': shape_ok,
            'identity': expected_identity, 'tables_checked': len(checks), 'checks': checks,
            'raw_rows_checked': len(snapshot['raw']), 'original_cells_checked': sum(len(row['payload']) for row in snapshot['raw']),
            'business_cells_checked': sum(len(row['properties']) for row in snapshot['nodes']),
            'nodes_checked': len(snapshot['nodes']), 'relations_checked': len(snapshot['relations']),
            'resolved_relations': sum(row['resolution'] == 'resolved' for row in snapshot['relations']),
            'unresolved_relations': sum(row['resolution'] != 'resolved' for row in snapshot['relations']),
            'unresolved_targets_remain_null': all(row['to_node'] is None for row in snapshot['relations'] if row['resolution'] != 'resolved'),
            'formal_adoption': False, 'raw_payload_public': False, 'data_nature': snapshot.get('dataset_nature', 'synthetic/unverified')}


class ReadbackError(ValueError):
    def __init__(self, report):
        super().__init__('Complete PostgreSQL readback differs; new schema transaction rolled back')
        self.report = report


def store_snapshot(connection, snapshot, rules, *, apply=False, progress=None):
    validate_snapshot(snapshot, require_full_batch=True)
    if connection.autocommit is not True:
        raise ValueError('An idle autocommit connection is required for one explicit transaction')
    plan = structure(snapshot, rules)
    emit = progress or (lambda value: None)
    created = False
    with connection.transaction():
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ' + ('' if apply else ', READ ONLY'))
        target = connection.execute('SELECT current_database(),current_user,inet_server_addr()::text,inet_server_port()').fetchone()
        guard_server(target)
        if apply:
            connection.execute('SELECT pg_advisory_xact_lock(28766219642049)')
        exists = connection.execute('SELECT to_regnamespace(%s)', (SCHEMA,)).fetchone()[0] is not None
        if not exists and not apply:
            raise ValueError('Reviewed batch schema is absent; verify never creates it')
        if not exists:
            created = True
            for statement in plan['statements']:
                connection.execute(statement)
            from psycopg.types.json import Jsonb
            for table, columns, rows in _rows(snapshot):
                count = 0
                with connection.cursor() as cursor:
                    with cursor.copy('COPY ' + qualified(table) + ' (' + _column_sql(columns) + ') FROM STDIN') as copy:
                        for row in rows:
                            copy.write_row(tuple(Jsonb(value) if isinstance(value, (dict, list)) else value for value in row))
                            count += 1
                emit({'stage': 'postgres_copy', 'table': table, 'rows': count})
            connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
            physical, _ = _physical(connection)
            document = {**identity(snapshot, rules), 'physical_schema_sha256': physical}
            connection.execute('INSERT INTO ' + qualified('batch_metadata') + ' (id,document) VALUES (%s,%s)', ('batch', Jsonb(document)))
        report = verify(connection, snapshot, rules, plan=plan)
        if report['status'] != 'passed':
            raise ReadbackError(report)
    report.update(schema_created=created, existing_schema_verified=not created,
                  transaction_committed=bool(created), database_write_performed=bool(created),
                  source_read_only=not created)
    return report
