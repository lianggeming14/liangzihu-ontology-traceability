"""Real RDF projection for the isolated review dataset, never formal adoption."""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import quote

from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD

NS = 'urn:lzo:fish-review:sample:v1:'
V = Namespace(NS)
C = Namespace('https://w3id.org/lzo/ontology/')
PROV = Namespace('http://www.w3.org/ns/prov#')
STATE = 'sample_not_formally_adopted'
ROOT_CLASS = str(C.DomainEntity)

LABELS = dict(zip(
    'farms ponds species cohorts pond_cohort_occupancy stocking_events transfer_events transfer_allocations mortality_events disposal_events fish_daily_balance feeding_events products partners purchases purchase_items inventory_movements opening_balances harvests harvest_grade_items sales sale_items harvest_sale_allocations settlements settlement_deductions cash_transactions cash_allocations cost_entries cost_allocations inventory_lot_status weather_observations devices device_installations device_calibrations pond_preparations water_observations patrol_events device_operations control_commands water_samples water_test_results water_operations device_maintenance growth_individuals growth_samples growth_grade_items health_cases case_observations diagnostic_tests treatment_events price_observations dictionaries pond_maintenance persons sources production_plans event_registry attachments attachment_links media_annotations documents document_versions spatial_layer_registry record_provenance'.split(),
    '养殖场 塘口 鱼种 养殖批次 塘口批次占用 放养事件 转塘事件 转塘分配 死亡事件 无害化处理 鱼群日结 投喂事件 产品 合作方 采购单 采购明细 库存流水 期初库存 起捕事件 起捕分级 销售单 销售明细 起捕销售分配 结算单 结算扣款 现金流水 现金分配 成本条目 成本分摊 库存批次状态 天气观测 设备 设备安装 设备校准 清塘准备 水质观测 巡塘事件 设备运行 控制指令 水样 水质检测 水体操作 设备维护 生长个体测量 生长采样 生长分级 健康病例 病例观察 诊断检测 治疗事件 价格观测 字典 塘口维护 人员 数据来源 生产计划 事件索引 附件 附件关联 媒体标注 文档 文档版本 空间图层 参考来源侧车'.split()))

# Domain concepts are independent of storage-table names. Source classes remain
# explicit leaves so two datasets can share Pond without equating their objects.
DOMAINS = {
    'DomainEntity': ('领域本体', None), 'BusinessEntity': ('业务对象', 'DomainEntity'),
    'Aquaculture': ('养殖本体', 'BusinessEntity'), 'Farm': ('养殖场', 'Aquaculture'),
    'Pond': ('鱼塘', 'Aquaculture'), 'Field': ('田块', 'BusinessEntity'),
    'Species': ('物种', 'Aquaculture'), 'Cohort': ('养殖批次', 'Aquaculture'),
    'ProductionEvent': ('生产事件', 'BusinessEntity'), 'Equipment': ('设备与设施', 'BusinessEntity'),
    'FinancialRecord': ('经营与财务', 'BusinessEntity'), 'InventoryRecord': ('产品与库存', 'BusinessEntity'),
    'HealthRecord': ('健康与防治', 'BusinessEntity'), 'Organization': ('组织与合作方', 'BusinessEntity'),
    'Person': ('人员', 'BusinessEntity'), 'Document': ('文档与证据', 'BusinessEntity'),
    'SpatialLayer': ('空间资料', 'BusinessEntity'), 'Observation': ('观测与测量', 'DomainEntity'),
    'EventIndex': ('事件索引', 'DomainEntity'), 'ReferenceRecord': ('参考结构', 'DomainEntity'),
}
TABLE_DOMAINS = {
    'farms': 'Farm', 'ponds': 'Pond', 'species': 'Species', 'cohorts': 'Cohort',
    'pond_cohort_occupancy': 'Aquaculture', 'production_plans': 'Aquaculture',
    'partners': 'Organization', 'persons': 'Person', 'spatial_layer_registry': 'SpatialLayer',
    'event_registry': 'EventIndex', 'record_provenance': 'ReferenceRecord', 'dictionaries': 'ReferenceRecord',
    **dict.fromkeys('water_observations weather_observations price_observations water_test_results growth_individuals fish_daily_balance growth_samples water_samples growth_grade_items'.split(), 'Observation'),
    **dict.fromkeys('products inventory_movements opening_balances inventory_lot_status'.split(), 'InventoryRecord'),
    **dict.fromkeys('purchases purchase_items sales sale_items settlements settlement_deductions cash_transactions cash_allocations cost_entries cost_allocations harvest_sale_allocations'.split(), 'FinancialRecord'),
    **dict.fromkeys('devices device_installations device_calibrations device_maintenance control_commands'.split(), 'Equipment'),
    **dict.fromkeys('health_cases case_observations diagnostic_tests treatment_events'.split(), 'HealthRecord'),
    **dict.fromkeys('sources attachments attachment_links media_annotations documents document_versions'.split(), 'Document'),
}

EXTRA_SOURCE_FIELDS = {
    'water_observations': {'uploaded_at', 'temperature_c_unit'},
    'feeding_events': {'quantity_kg_unit'}, 'patrol_events': {'uploaded_at'},
    'price_observations': {'uploaded_at', 'price_yuan_per_kg_unit'},
    'water_test_results': {'uploaded_at', 'value_unit'},
}


def expanded_schema(snapshot):
    schema = json.loads(json.dumps(snapshot['schema']))
    for row in snapshot['nodes']:
        table = row['table_name']
        for field in sorted(set(row['properties']) - set(schema['tables'][table]['columns'])):
            if field not in EXTRA_SOURCE_FIELDS.get(table, set()): raise ValueError('Unknown source field')
            schema['tables'][table]['columns'][field] = {'type': 'string',
                'description': '额外来源字段（主字段字典未声明）：' + field, 'source_dictionary_declared': False}
    return schema


def uri(kind, *parts):
    return URIRef(NS + kind + ':' + ':'.join(quote(str(p), safe='') for p in parts))


def role(table):
    if table == 'record_provenance': return 'reference'
    if table == 'event_registry': return 'index'
    return 'telemetry' if table in {'water_observations', 'weather_observations', 'price_observations',
        'water_test_results', 'growth_individuals', 'fish_daily_balance'} else 'entity'


def datatype(spec):
    if spec.get('format') == 'date-time': return XSD.dateTime
    if spec.get('format') == 'date': return XSD.date
    kind = spec.get('type', 'string')
    if isinstance(kind, list): kind = next((item for item in kind if item != 'null'), 'string')
    return {'integer': XSD.integer, 'number': XSD.decimal, 'boolean': XSD.boolean}.get(kind, XSD.string)


def typed_literal(value, spec):
    target = datatype(spec)
    if target == XSD.decimal:
        try:
            number = Decimal(str(value))
            if not number.is_finite(): raise ValueError('Non-finite decimal')
        except InvalidOperation: raise ValueError('Invalid decimal') from None
        lexical = format(number, 'f')
        if '.' in lexical: lexical = lexical.rstrip('0').rstrip('.')
        if number == 0: lexical = '0'
        if '.' not in lexical: lexical += '.0'
    elif target == XSD.integer:
        if isinstance(value, bool) or Decimal(str(value)) != int(value): raise ValueError('Invalid integer')
        lexical = str(int(value))
    elif target == XSD.boolean:
        if not (type(value) is bool or type(value) is str and value in ('true', 'false')):
            raise ValueError('Invalid boolean')
        lexical = 'true' if value is True or value == 'true' else 'false'
    else:
        lexical = str(value)
    return Literal(lexical, datatype=target, normalize=False)


def triples(subject, **values):
    for key, value in values.items():
        if value is not None:
            yield subject, V[key], value if isinstance(value, (URIRef, Literal)) else Literal(value)


def project(snapshot):
    """Yield complete RDF; SQL rows are inputs, never masquerading as RDF nodes."""
    schema, nodes = expanded_schema(snapshot)['tables'], {r['node_id']: r for r in snapshot['nodes']}
    raw = {(r['table_name'], r['row_number']): r for r in snapshot['raw']}
    if len(raw) != len(snapshot['raw']) or len(nodes) != len(snapshot['nodes']):
        raise ValueError('Duplicate physical source or instance identity')
    dataset = URIRef(NS + 'dataset:' + snapshot['package_sha256'])
    yield dataset, RDF.type, OWL.Ontology
    yield dataset, RDFS.label, Literal('武昌鱼审查样本本体', lang='zh')
    yield from triples(dataset, packageSHA256=snapshot['package_sha256'], adoptionStatus=STATE,
                       sourceSchema='fish_review_10pct_v1', formalAdoption=Literal(False))
    for name, (label, parent) in DOMAINS.items():
        subject = C[name]
        yield subject, RDF.type, OWL.Class
        yield subject, RDFS.label, Literal(label, lang='zh')
        yield from triples(subject, conceptRole='domain')
        if parent: yield subject, RDFS.subClassOf, C[parent]
    for name, label in [('SourceRecord', '来源物理行'), ('RelationRecord', '来源关联记录')]:
        yield V[name], RDF.type, OWL.Class
        yield V[name], RDFS.label, Literal(label, lang='zh')
        yield V[name], RDFS.subClassOf, PROV.Entity
    for table, spec in schema.items():
        cls = uri('class', table)
        yield cls, RDF.type, OWL.Class
        yield cls, RDFS.subClassOf, C[TABLE_DOMAINS.get(table, 'ProductionEvent')]
        yield cls, RDFS.label, Literal(LABELS.get(table, table), lang='zh')
        yield from triples(cls, sourceTable=table, conceptRole=role(table))
        for field, desc in spec['columns'].items():
            prop = uri('property', table, field)
            yield prop, RDF.type, OWL.DatatypeProperty
            yield prop, RDFS.domain, cls
            yield prop, RDFS.range, datatype(desc)
            yield prop, RDFS.label, Literal(desc.get('description') or field, lang='zh')
            yield from triples(prop, sourceField=field, sourceTable=table, unit=desc.get('unit'),
                requiredCondition=desc.get('required_condition'),
                sourceDictionaryDeclared=Literal(desc.get('source_dictionary_declared', True)))
            raw_prop = uri('raw', table, field)
            yield raw_prop, RDF.type, OWL.DatatypeProperty
            yield raw_prop, RDFS.domain, V.SourceRecord
            yield raw_prop, RDFS.range, XSD.string
    for row in snapshot['raw']:
        subject = uri('source', row['table_name'], row['row_number'])
        yield subject, RDF.type, V.SourceRecord
        yield subject, RDF.type, PROV.Entity
        yield subject, PROV.wasDerivedFrom, dataset
        yield from triples(subject, sourceTable=row['table_name'], rowNumber=row['row_number'],
            sourcePK=row['source_pk'], inputStatus=row['status'], sampleReason=row['sample_reason'],
            issues=Literal(json.dumps(row['issues'], ensure_ascii=False, separators=(',', ':')), datatype=RDF.JSON),
            packageSHA256=snapshot['package_sha256'])
        for field, value in row['payload'].items():
            if not isinstance(value, str): raise ValueError('Original source cells must be strings')
            yield subject, uri('raw', row['table_name'], field), Literal(value)
    for row in snapshot['nodes']:
        table = row['table_name']
        source = raw.get((table, row['source_row']))
        if source is None or source['source_pk'] != row['source_pk'] or source['status'] not in ('accepted', 'needs_review'):
            raise ValueError('Canonical instance has no exact usable source row')
        if set(row['properties']) - set(schema[table]['columns']): raise ValueError('Unknown source field')
        subject = uri('instance', row['node_id'])
        yield subject, RDF.type, uri('class', table)
        name = next((row['properties'].get(key) for key in ('name', 'title', 'label') if row['properties'].get(key)), row['source_pk'])
        yield subject, RDFS.label, Literal(str(name))
        yield subject, PROV.wasDerivedFrom, uri('source', table, row['source_row'])
        yield from triples(subject, sourceTable=table, sourcePK=row['source_pk'], sampleUUID=row['node_id'],
            dataNature=row['nature'], adoptionStatus=STATE, recordRole=row['role'])
        for field, desc in schema[table]['columns'].items():
            prop, value = uri('property', table, field), row['properties'].get(field)
            if value is None: yield subject, V.missingField, prop
            else: yield subject, prop, typed_literal(value, desc)
    relation_types = {}
    for edge in snapshot['relations']:
        source = nodes.get(edge['from_node'])
        if source is None: raise ValueError('Unknown relationship source')
        table, target = source['table_name'], edge['target_table']
        key = (table, edge['field_name'], target)
        predicate = uri('relation', *key)
        inverse = URIRef(str(predicate) + ':inverse')
        if key not in relation_types:
            relation_types[key] = predicate
            yield predicate, RDF.type, OWL.ObjectProperty
            yield predicate, RDFS.domain, uri('class', table)
            if target in schema: yield predicate, RDFS.range, uri('class', target)
            yield predicate, RDFS.label, Literal(edge['field_name'] + ' → ' + LABELS.get(target, str(target)))
            yield predicate, OWL.inverseOf, inverse
            yield inverse, RDF.type, OWL.ObjectProperty
            yield inverse, RDFS.range, uri('class', table)
            if target in schema: yield inverse, RDFS.domain, uri('class', target)
            yield from triples(predicate, sourceField=edge['field_name'], sourceTable=table, targetTable=target)
        statement = uri('edge', edge['edge_id'])
        yield statement, RDF.type, V.RelationRecord
        yield statement, RDF.subject, uri('instance', edge['from_node'])
        yield statement, RDF.predicate, predicate
        yield statement, PROV.wasDerivedFrom, uri('source', table, edge['source_row'])
        yield from triples(statement, sourceField=edge['field_name'], targetTable=target, targetPK=edge['target_pk'],
            resolution=edge['resolution'], rowNumber=edge['source_row'], listIndex=edge.get('list_index'))
        if edge['resolution'] == 'resolved':
            bound = nodes.get(edge['to_node'])
            if bound is None or bound['table_name'] != target or bound['source_pk'] != edge['target_pk']:
                raise ValueError('Resolved relationship target identity or class mismatch')
            target_uri = uri('instance', edge['to_node'])
            yield statement, RDF.object, target_uri
            yield uri('instance', edge['from_node']), predicate, target_uri
            yield target_uri, inverse, uri('instance', edge['from_node'])
        elif edge['to_node'] is not None:
            raise ValueError('Unresolved relationship must not bind a target')


def term_key(term):
    """RDF 1.1 term identity: simple and xsd:string literals are the same term.

    Numeric precision/lexical forms are intentionally not normalized here.
    Jena readback must preserve the actual generated RDF terms.
    """
    if isinstance(term, URIRef): return ['iri', str(term)]
    if not isinstance(term, Literal): raise ValueError('Blank nodes are forbidden in deterministic sample graph')
    return ['literal', str(term), str(term.datatype or XSD.string) if not term.language else '', term.language or '']


def triple_digest(s, p, o):
    return hashlib.sha256(json.dumps([term_key(t) for t in (s, p, o)], ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).digest()


class Navigation:
    """Collect only review-visible RDF from the real Jena readback stream."""
    def __init__(self):
        self.records = defaultdict(lambda: defaultdict(list))

    def add(self, subject, predicate, value):
        s, p = str(subject), str(predicate)
        if not (s.startswith(NS) or s.startswith(str(C))): return
        if p.startswith(NS + 'raw:'): return  # Raw strings remain in local RDF only.
        if s.startswith(NS + 'raw:'): return
        self.records[s][p].append(value)

    def finish(self):
        records = self.records
        def one(subject, predicate, default=None):
            values = records.get(subject, {}).get(str(predicate), [])
            return str(values[0]) if values else default
        def integer(subject, predicate):
            value = one(subject, predicate)
            return int(value) if value is not None else None
        concepts, instance_by_iri, tables = {}, {}, {}
        package = None
        for subject, values in records.items():
            if subject.startswith(NS + 'dataset:'): package = one(subject, V.packageSHA256)
            if OWL.Class in values.get(str(RDF.type), []) and one(subject, V.conceptRole) is not None:
                table = one(subject, V.sourceTable)
                concepts[subject] = {'iri': subject, 'label': one(subject, RDFS.label, subject),
                    'parent_iri': one(subject, RDFS.subClassOf), 'children': [], 'table': table,
                    'role': one(subject, V.conceptRole), 'instance_count': 0, 'total_instance_count': 0,
                    'instances_path': 'classes/' + table + '.json' if table else None}
                if table: tables[table] = {'contract': 'fish-rdf-review/1', 'class_iri': subject, 'instances': []}
        for subject, values in records.items():
            if not subject.startswith(NS + 'instance:'): continue
            cls, table = one(subject, RDF.type), one(subject, V.sourceTable)
            if cls not in concepts or table not in tables: raise ValueError('RDF instance has no declared source class')
            source = one(subject, PROV.wasDerivedFrom)
            props = []
            missing = {str(item) for item in values.get(str(V.missingField), [])}
            for prop in sorted(set(p for p in values if p.startswith(NS + 'property:')) | missing):
                field = one(prop, V.sourceField)
                dtype = one(prop, RDFS.range)
                actual = values.get(prop, [])
                value = str(actual[0]) if actual else None
                if value is not None and dtype == str(XSD.boolean): value = value == 'true'
                if value is not None and dtype == str(XSD.integer): value = int(value)
                props.append({'iri': prop, 'field': field, 'label': one(prop, RDFS.label, field),
                    'value': value, 'datatype': dtype, 'unit': one(prop, V.unit), 'nature': one(subject, V.dataNature)})
            item = {'iri': subject, 'id': one(subject, V.sourcePK), 'uuid': one(subject, V.sampleUUID),
                'table': table, 'label': one(subject, RDFS.label), 'class_iri': cls,
                'nature': one(subject, V.dataNature), 'adoption_status': one(subject, V.adoptionStatus),
                'properties': props, 'outgoing': [], 'incoming': [], 'unresolved_relations': [],
                'provenance': {'source_record_iri': source, 'table': table, 'row_number': integer(source, V.rowNumber),
                    'package_sha256': one(source, V.packageSHA256), 'status': one(source, V.inputStatus),
                    'sample_reason': one(source, V.sampleReason), 'issues': json.loads(one(source, V.issues, '[]'))}}
            if item['adoption_status'] != STATE: raise ValueError('Unexpected adoption status')
            instance_by_iri[subject] = item
            tables[table]['instances'].append(item)
            concepts[cls]['instance_count'] += 1
        relation_count = resolved_count = 0
        for subject in records:
            if not subject.startswith(NS + 'edge:'): continue
            relation_count += 1
            source, target = one(subject, RDF.subject), one(subject, RDF.object)
            if source not in instance_by_iri: raise ValueError('Unknown RDF relationship source')
            predicate = one(subject, RDF.predicate)
            edge = {'iri': predicate, 'edge_iri': subject, 'field': one(subject, V.sourceField),
                'label': one(predicate, RDFS.label), 'resolution': one(subject, V.resolution),
                'source_row': integer(subject, V.rowNumber), 'list_index': integer(subject, V.listIndex)}
            if target is not None:
                if edge['resolution'] != 'resolved' or target not in instance_by_iri:
                    raise ValueError('Invalid RDF relationship target')
                src, dst = instance_by_iri[source], instance_by_iri[target]
                src['outgoing'].append({**edge, 'target_iri': target, 'target_id': dst['id'],
                    'target_label': dst['label'], 'target_class_iri': dst['class_iri']})
                dst['incoming'].append({**edge, 'source_iri': source, 'source_id': src['id'],
                    'source_label': src['label'], 'source_class_iri': src['class_iri']})
                resolved_count += 1
            else:
                instance_by_iri[source]['unresolved_relations'].append({**edge,
                    'target_table': one(subject, V.targetTable), 'target_id': one(subject, V.targetPK)})
        for item in concepts.values():
            if item['parent_iri'] in concepts: concepts[item['parent_iri']]['children'].append(item['iri'])
        def count(iri, visited):
            if iri in visited: raise ValueError('Concept hierarchy cycle')
            item = concepts[iri]
            item['children'].sort()
            item['total_instance_count'] = item['instance_count'] + sum(count(child, visited | {iri}) for child in item['children'])
            return item['total_instance_count']
        for iri, item in concepts.items():
            if item['parent_iri'] not in concepts: count(iri, set())
        for table in tables.values():
            table['instances'].sort(key=lambda item: (item['id'], item['iri']))
            for item in table['instances']:
                for name in ('outgoing', 'incoming', 'unresolved_relations'):
                    item[name].sort(key=lambda edge: (edge['field'], edge['edge_iri']))
        manifest = {'contract': 'fish-rdf-review/1', 'namespace': NS, 'root_iri': ROOT_CLASS,
            'package_sha256': package, 'formal_adoption': False, 'jena_verified': False,
            'counts': {'instances': len(instance_by_iri), 'relations': relation_count,
                'resolved_relations': resolved_count, 'classes': len(concepts), 'source_classes': len(tables)},
            'concepts': sorted(concepts.values(), key=lambda item: item['iri'])}
        return manifest, tables
