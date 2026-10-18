"""Transactional source-record mapping, without source SQL execution or AI inference.

Source keys identify records inside a tenant/source/table namespace. Ontology UUIDs
are always generated here. Profiles are immutable; revisions keep source evidence,
entity snapshots and temporal relationship history. A snapshot timestamp is the
time a source representation was witnessed, never proof of a business event time.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from urllib.parse import quote

from jsonschema import Draft202012Validator, FormatChecker
from .core_intake import IntakeService
from .ontology_core import validate_property_value
from .service import DomainError, _hash, _id, _json, _now, _time, _unpack, _uuid

SOURCE_SCHEMAS = json.loads((Path(__file__).resolve().parents[1] / 'contracts' / 'source-mapping-schemas.json').read_text(encoding='utf-8'))
_JSON_FIELDS = {'source_key','key_contract','type_ref','source_values','managed_properties','entity_snapshot','response'}
_WRITE_ROLES = {'admin','ontology_admin'}


def _row(value):
    result = _unpack(value)
    if result:
        for key in _JSON_FIELDS:
            if isinstance(result.get(key), str):
                result[key] = json.loads(result[key])
    return result


def _validate(action, payload):
    try:
        if len(_json(payload).encode('utf-8')) > 2 * 1024 * 1024:
            raise DomainError(413, 'source_batch_too_large', '来源映射请求超过 2 MiB')
    except (TypeError, ValueError, RecursionError):
        raise DomainError(422, 'invalid_json', '输入必须为有限且有界的 JSON 值')
    errors = list(Draft202012Validator(SOURCE_SCHEMAS[action], format_checker=FormatChecker()).iter_errors(payload))
    if errors:
        raise DomainError(422, 'schema_validation_failed', '来源映射输入不符合契约',
                          [{'path':list(e.path),'message':e.message} for e in errors[:20]])


def _key_contract(table):
    return {field:table.get('key_types', {}).get(field, 'string') for field in table['primary_key']}


def _key(table, values):
    result = {}
    for field, kind in _key_contract(table).items():
        value = values.get(field)
        if kind == 'uuid':
            if not isinstance(value,str):
                raise DomainError(422, 'invalid_source_key', 'UUID 主键必须使用字符串', {'field':field})
            value = _uuid(value, field)
        elif kind == 'integer':
            if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r'-?(0|[1-9][0-9]*)', str(value)):
                raise DomainError(422, 'invalid_source_key', '整数主键必须使用十进制整数字符串或安全整数', {'field':field})
            if isinstance(value, int) and abs(value) > 9007199254740991:
                raise DomainError(422, 'unsafe_integer_key', '超过 JavaScript 安全整数范围的主键必须传字符串', {'field':field})
            if len(str(value)) > 200:
                raise DomainError(422, 'invalid_source_key', '主键超过长度限制', {'field':field})
            value = str(int(value))
        elif not isinstance(value, str) or not value or len(value) > 500:
            raise DomainError(422, 'invalid_source_key', '字符串主键不能为空且不能超过 500 字符', {'field':field})
        result[field] = value
    return result


def _convert(value, transform):
    if value is None:
        return None
    if transform == 'decimal':
        if isinstance(value, (bool, float)) or not isinstance(value, (str, int)):
            raise DomainError(422, 'source_decimal_precision', '十进制数必须使用字符串或整数；不接受浮点输入')
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise DomainError(422, 'source_decimal_precision', '无法解析十进制数')
        if not number.is_finite() or len(number.as_tuple().digits) > 100 or abs(number.as_tuple().exponent) > 100:
            raise DomainError(422, 'source_decimal_precision', '十进制数超出支持精度')
        return format(number, 'f')
    if transform == 'integer':
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r'-?(0|[1-9][0-9]*)', str(value)):
            raise DomainError(422, 'source_integer_type', '整数字段不接受小数或隐式布尔转换')
        if isinstance(value, int) and abs(value) > 9007199254740991:
            raise DomainError(422, 'source_integer_precision', '大整数应从字符串导入')
        if len(str(value)) > 20 or not -9223372036854775808 <= int(value) <= 9223372036854775807:
            raise DomainError(422, 'source_integer_precision', '整数超过有符号 64 位范围')
        return int(value)
    if transform == 'datetime':
        return _time(value, 'source datetime')
    if transform == 'date':
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise DomainError(422, 'source_date_type', '日期必须使用 YYYY-MM-DD')
        try:
            date.fromisoformat(value)
        except ValueError:
            raise DomainError(422, 'source_date_type', '日期不存在')
        return value
    if transform == 'uuid':
        if not isinstance(value,str):
            raise DomainError(422, 'source_uuid_type', 'UUID 属性必须使用字符串')
        return _uuid(value, 'source UUID')
    if transform == 'text_array':
        if not isinstance(value, list) or len(value) > 100 or not all(isinstance(x, str) and len(x) <= 10000 for x in value):
            raise DomainError(422, 'source_array_type', '文本数组最多包含 100 个字符串')
        # An empty SQL array does not mean a known member. Preserve [] in source
        # evidence while explicitly omitting the ontology many-valued attribute.
        return value or None
    return deepcopy(value)


class SourceMappingService(IntakeService):
    ACTION_ROLES = {**IntakeService.ACTION_ROLES,
                    'register_source_profile':_WRITE_ROLES,
                    'import_source_batch':_WRITE_ROLES,
                    'install_source_bundle':_WRITE_ROLES}
    input_schemas = {**IntakeService.input_schemas, **SOURCE_SCHEMAS}

    def mutate(self, action, tenant, actor, payload, idempotency_key):
        if action in SOURCE_SCHEMAS:
            _validate(action, payload)
        return super().mutate(action, tenant, actor, payload, idempotency_key)

    def _profile(self, tx, tenant, source, profile, version):
        row = _row(tx.execute('SELECT * FROM source_profiles WHERE tenant_id=%s AND source_id=%s AND profile_id=%s AND version=%s',
                             (tenant, source, profile, version)).fetchone())
        if not row:
            raise DomainError(404, 'source_profile_not_found', '当前租户未登记该来源映射版本')
        row['id'] = 'urn:source-profile:'+':'.join(quote(value,safe='') for value in (source,profile,version))
        return row

    def _definitions(self, tx, tenant, table):
        ref = table['type_ref']
        package = self._get_package(tx, tenant, ref['package_id'], ref['version'])
        type_def = next((x for x in package['types'] if x['type_id'] == ref['type_id']), None)
        if not type_def:
            raise DomainError(422, 'source_type_not_found', '映射目标类不存在', {'table':table['table'],'type_ref':ref})
        properties = {x['property_id']:x for x in package['properties'] if ref['type_id'] in x['applies_to'] and x['usage'] == 'attribute'}
        return type_def, properties

    def _check_binding_contract(self, tx, tenant, source_id, table):
        # Check the namespace before computing a new key. Otherwise a changed
        # PK field or normalization rule could miss the old hash and create a
        # second identity, bypassing the per-record conflict check.
        prior = _row(tx.execute('SELECT key_contract,type_ref FROM source_bindings WHERE tenant_id=%s AND source_id=%s AND source_table=%s LIMIT 1',
                               (tenant,source_id,table['table'])).fetchone())
        if prior and (prior['key_contract'] != _key_contract(table) or prior['type_ref'] != table['type_ref']):
            raise DomainError(409, 'source_type_migration_required', '此来源表已有绑定，主键规则及目标类版本必须保持一致；变更需专门迁移')

    def _do_register_source_profile(self, tx, tenant, actor, p):
        _validate('register_source_profile', p)
        prior = _row(tx.execute('SELECT * FROM source_profiles WHERE tenant_id=%s AND source_id=%s AND profile_id=%s AND version=%s',
                               (tenant,p['source_id'],p['profile_id'],p['version'])).fetchone())
        if prior:
            if prior['content_hash'] != _hash(p):
                raise DomainError(409, 'immutable_source_profile', '已登记的来源映射版本不可覆盖，请创建新版本')
            return self._profile(tx,tenant,p['source_id'],p['profile_id'],p['version'])
        tables = {x['table']:x for x in p['tables']}
        if len(tables) != len(p['tables']):
            raise DomainError(422, 'duplicate_source_table', '来源表映射不能重复')
        identity_types = {}
        for table in p['tables']:
            self._check_binding_contract(tx,tenant,p['source_id'],table)
            type_def, properties = self._definitions(tx, tenant, table)
            identity_types[table['table']] = type_def['identity_type']
            if len(set(table['primary_key'])) != len(table['primary_key']) or set(table.get('key_types',{})) - set(table['primary_key']):
                raise DomainError(422, 'invalid_key_contract', '主键字段重复或 key_types 包含非主键字段')
            source_fields = [x['source_field'] for x in table['fields']]
            property_ids = [x['property_id'] for x in table['fields']]
            deferred = [x['field'] for x in table['deferred_fields']]
            rejected = table['rejected_fields']
            if len(set(source_fields)) != len(source_fields) or len(set(property_ids)) != len(property_ids) or len(set(deferred)) != len(deferred) or len(set(rejected)) != len(rejected):
                raise DomainError(422, 'duplicate_source_mapping', '来源字段、属性或字段策略重复')
            consumed = set(source_fields) | set(table['primary_key']) | {table.get('name_field')}
            consumed |= {x['source_unit_field'] for x in table['fields'] if 'source_unit_field' in x}
            consumed |= {field for relation in table['relations'] for field in relation['fields']}
            if set(deferred)&(consumed|set(rejected)) or set(rejected)&consumed:
                raise DomainError(422, 'source_field_policy_conflict', '字段不能同时映射、暂存或拒绝')
            for field in table['fields']:
                definition = properties.get(field['property_id'])
                if not definition:
                    raise DomainError(422, 'source_property_not_found', '属性未属于映射目标类或不是 attribute', {'table':table['table'],'property_id':field['property_id']})
                if 'unit' in definition:
                    if field.get('source_unit') != definition['unit']:
                        raise DomainError(422, 'source_unit_declaration', '带单位属性必须显式声明相同的 source_unit；本接口不隐式换算单位',
                                          {'property_id':field['property_id'],'expected':definition['unit'],'declared':field.get('source_unit')})
                elif 'source_unit' in field or 'source_unit_field' in field:
                    raise DomainError(422, 'unexpected_source_unit', '目标属性未定义单位，不能声明来源单位', {'property_id':field['property_id']})
                if field.get('source_unit_field') == field['source_field']:
                    raise DomainError(422, 'source_unit_field_conflict', '数值字段与单位字段必须分开声明')
                expected = {'decimal':'decimal','integer':'integer','datetime':'datetime','date':'string','uuid':'string','text_array':'string'}.get(field.get('transform'))
                if expected and (definition['value_type'] != expected or (field.get('transform') == 'text_array') != (definition.get('cardinality','single') == 'many')):
                    raise DomainError(422, 'source_transform_mismatch', '转换类型或数组基数与本体属性定义不一致', {'property_id':field['property_id']})
            relation_keys = [x['relation_key'] for x in table['relations']]
            if len(set(relation_keys)) != len(relation_keys):
                raise DomainError(422, 'duplicate_source_relation', '同一表的关系映射键不能重复')
        for table in p['tables']:
            for relation in table['relations']:
                target = tables.get(relation['target_table'])
                if not target or relation['target_fields'] != target['primary_key'] or len(relation['fields']) != len(relation['target_fields']) or len(set(relation['fields'])) != len(relation['fields']):
                    raise DomainError(422, 'invalid_source_reference', '关系必须按顺序引用已配置目标表的完整主键', {'table':table['table'],'relation_key':relation['relation_key']})
                ref = relation['predicate_ref']
                package = self._get_package(tx, tenant, ref['package_id'], ref['version'])
                predicate = next((x for x in package['predicates'] if x['predicate_id'] == ref['predicate_id']), None)
                if not predicate:
                    raise DomainError(422, 'source_predicate_not_found', '关系映射引用的本体关系不存在')
                for name, side in ((table['table'],'subject'),(target['table'],'object')):
                    if identity_types[name] not in predicate[side+'_types'] and '*' not in predicate[side+'_types']:
                        raise DomainError(422, 'source_relation_type_mismatch', '来源关系端点类不符合本体关系约束', {'relation_key':relation['relation_key'],'endpoint':side})
                    allowed = predicate.get(side+'_semantic_types')
                    type_ref = tables[name]['type_ref']
                    if allowed and (type_ref['package_id'] != ref['package_id'] or type_ref['version'] != ref['version'] or type_ref['type_id'] not in allowed):
                        raise DomainError(422, 'source_relation_type_mismatch', '来源关系端点语义类不符合本体关系约束', {'relation_key':relation['relation_key'],'endpoint':side})
        tx.execute('INSERT INTO source_profiles(tenant_id,source_id,profile_id,version,definition,content_hash,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                   (tenant,p['source_id'],p['profile_id'],p['version'],_json(p),_hash(p),_now(),str(actor['id'])))
        return self._profile(tx, tenant, p['source_id'], p['profile_id'], p['version'])

    def _do_install_source_bundle(self, tx, tenant, actor, p):
        _validate('install_source_bundle', p)
        seen = set()
        for package in p['packages']:
            key = (package.get('package_id'),package.get('version'))
            if key in seen:
                raise DomainError(422, 'duplicate_bundle_package', '安装包包含重复本体版本')
            seen.add(key)
            self._do_register_package(tx, tenant, actor, package)
        profile = self._do_register_source_profile(tx, tenant, actor, p['profile'])
        result = {'id':profile['id'],'profile':profile,'package_count':len(p['packages']),'table_count':len(p['profile']['tables'])}
        if 'batch' in p:
            if any(p['batch'][k] != p['profile'][k] for k in ('source_id','profile_id','version')):
                raise DomainError(422, 'bundle_profile_mismatch', '安装包与批次必须引用相同来源映射版本')
            result['batch'] = self._do_import_source_batch(tx, tenant, actor, p['batch'])
            result['id'] = result['batch']['id']
        return result

    def _binding(self, tx, tenant, source, table, key):
        row = _row(tx.execute('SELECT * FROM source_bindings WHERE tenant_id=%s AND source_id=%s AND source_table=%s AND key_hash=%s',
                             (tenant,source,table,_hash(key))).fetchone())
        if row and row['source_key'] != key:
            raise DomainError(409, 'source_key_hash_collision', '来源身份摘要冲突，不能继续绑定')
        return row

    def _prepare_record(self, tx, tenant, p, table, record, index):
        self._check_binding_contract(tx,tenant,p['source_id'],table)
        key = _key(table, record['values'])
        binding = self._binding(tx, tenant, p['source_id'], table['table'], key)
        expected = record.get('expected_revision')
        if not binding and expected not in (None,0):
            raise DomainError(409, 'source_revision_conflict', '新来源记录的 expected_revision 应为 0', {'current_revision':0})
        if binding and (binding['key_contract'] != _key_contract(table) or binding['type_ref'] != table['type_ref']):
            raise DomainError(409, 'source_type_migration_required', '已绑定记录的主键规则和目标类版本不能隐式变更，请先制定本体迁移方案')
        if binding and binding['data_nature'] != p.get('data_nature','unspecified'):
            raise DomainError(409, 'source_data_nature_conflict', '来源记录的数据性质不可静默变更；生产、测试和合成数据请使用独立来源命名空间')
        rejected = sorted(set(record['values']) & set(table['rejected_fields']))
        if rejected:
            raise DomainError(422, 'source_field_rejected', '输入含禁止接入字段；请在源端移除后重试', {'fields':rejected})
        allowed = set(table['primary_key']) | {table.get('name_field')} | {x['source_field'] for x in table['fields']} | {x['field'] for x in table['deferred_fields']} | {f for r in table['relations'] for f in r['fields']}
        allowed |= {x['source_unit_field'] for x in table['fields'] if 'source_unit_field' in x}
        unknown = sorted(set(record['values']) - allowed)
        if unknown:
            raise DomainError(422, 'unmapped_source_field', '来源字段未声明映射或暂存策略', {'fields':unknown})
        values = deepcopy(binding['source_values']) if binding else {}
        values.update(deepcopy(record['values']))
        values.update(key)
        # A narrower profile must never silently retain source data that it no
        # longer knows how to handle. Admin must explicitly map or defer it.
        if set(values) - allowed:
            raise DomainError(422, 'profile_dropped_fields', '新映射遗漏了已接入字段，请显式保留映射或暂存策略', {'fields':sorted(set(values)-allowed)})
        digest = _hash({'values':values,'profile_id':p['profile_id'],'version':p['version'],'data_nature':p.get('data_nature','unspecified')})
        unchanged = bool(binding and binding['payload_hash'] == digest)
        if binding and not unchanged:
            if expected != binding['revision']:
                raise DomainError(409, 'source_revision_conflict', '来源内容已存在且不同，修改需提供当前 expected_revision', {'current_revision':binding['revision']})
            if _time(p['observed_at']) <= _time(binding['observed_at']):
                raise DomainError(409, 'source_time_regression', '修订快照时间必须晚于上一已提交快照', {'last_observed_at':binding['observed_at']})
        type_def, definitions = self._definitions(tx, tenant, table)
        attrs = {}
        for mapping in table['fields']:
            field = mapping['source_field']
            if field not in values:
                continue
            value = _convert(values[field], mapping.get('transform','identity'))
            if value is None:
                continue
            definition = definitions[mapping['property_id']]
            unit_field = mapping.get('source_unit_field')
            if unit_field and values.get(unit_field) != mapping['source_unit']:
                raise DomainError(422, 'source_unit_mismatch', '来源记录单位缺失或不符合已声明单位；请先显式换算再接入',
                                  {'source_field':field,'source_unit_field':unit_field,'expected':mapping['source_unit'],'actual':values.get(unit_field)})
            typed = {'value':value}
            if 'unit' in definition:
                typed['unit'] = definition['unit']
            validate_property_value(definition, typed, 'attribute')
            attrs[mapping['property_id']] = typed
        name = values.get(table.get('name_field'))
        if name is None:
            name = table.get('name_prefix',table['table']) + ' #' + _hash(key)[:12]
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise DomainError(422, 'invalid_source_name', '来源名称必须是 1 至 500 字符的非空字符串')
        if binding:
            entity = self._entity(tx, tenant, binding['entity_key'])
            if entity['revision'] != binding['entity_revision']:
                raise DomainError(409, 'source_entity_conflict', '绑定对象在来源流程之外被修改，需先人工核对', {'entity_key':entity['entity_key'],'current_entity_revision':entity['revision'],'mapped_entity_revision':binding['entity_revision']})
            preserved = {k:v for k,v in entity['attributes'].items() if k not in binding['managed_properties']}
            preserved.update(attrs)
            attrs = preserved
        if p.get('data_nature') in {'synthetic','test'}:
            attrs['synthetic'] = True
        elif binding and 'synthetic' in attrs:
            # Do not silently reclassify synthetic/test identities as field
            # data merely because the next caller changed a batch label.
            raise DomainError(409, 'source_data_nature_conflict', '合成或测试对象不可重标为现场数据，请使用独立来源命名空间')
        return {'index':index,'table':table,'key':key,'binding':binding,'values':values,'digest':digest,'attrs':attrs,
                'name':name.strip(),'identity_type':type_def['identity_type'],'unchanged':unchanged,
                'deferred_fields':[x for x in table['deferred_fields'] if x['field'] in values]}

    def _store_record(self, tx, tenant, actor, p, item):
        binding, table = item['binding'], item['table']
        if item['unchanged']:
            item['status'] = 'unchanged'
            return
        now, snapshot = _now(), _time(p['observed_at'])
        revision = binding['revision'] + 1 if binding else 1
        raw = {'format':'source-record/1','source_id':p['source_id'],'table':table['table'],'source_key':item['key'],
               'profile_id':p['profile_id'],'version':p['version'],'batch_id':p['batch_id'],'source_revision':revision,
               'observed_at':snapshot,'values':item['values'],'deferred_fields':item['deferred_fields'],
               'data_nature':p.get('data_nature','unspecified'),'submitted_values':p['records'][item['index']]['values'],
               'expected_revision':p['records'][item['index']].get('expected_revision')}
        evidence = self._do_create_evidence(tx,tenant,actor,{'kind':'structured','uri':'urn:source-record:sha256:'+_hash(raw),
                         'content_hash':_hash(raw),'source_id':p['source_id'],
                         'metadata':{'receipt_format':'source-record/1','receipt':raw,'canonical_json':_json(raw),'information_nature':'source_snapshot','data_nature':p.get('data_nature','unspecified'),'causal_claim':False}})
        managed = [x['property_id'] for x in table['fields']]
        if binding:
            entity = self._entity(tx,tenant,binding['entity_key'])
            check = dict(entity,attributes=item['attrs'])
            self._check_attributes(tx,tenant,check,now)
            tx.execute('UPDATE entities SET name=%s,attributes=%s,revision=revision+1 WHERE tenant_id=%s AND entity_key=%s',
                       (item['name'],_json(item['attrs']),tenant,entity['entity_key']))
            entity = self._entity(tx,tenant,entity['entity_key'])
            tx.execute('UPDATE source_bindings SET revision=%s,entity_revision=%s,profile_id=%s,profile_version=%s,source_values=%s,payload_hash=%s,evidence_id=%s,managed_properties=%s,observed_at=%s,updated_at=%s WHERE tenant_id=%s AND id=%s',
                       (revision,entity['revision'],p['profile_id'],p['version'],_json(item['values']),item['digest'],evidence['id'],_json(managed),snapshot,now,tenant,binding['id']))
            item['status'] = 'updated'
        else:
            assignment = dict(table['type_ref'], valid_from=snapshot)
            entity = self._do_create_entity(tx,tenant,actor,{'entity_type':item['identity_type'],'name':item['name'],
                                                          'attrs':item['attrs'],'semantic_types':[assignment]})
            binding_id = _id()
            tx.execute('INSERT INTO source_bindings(tenant_id,id,source_id,source_table,key_hash,source_key,key_contract,entity_key,type_ref,revision,entity_revision,profile_id,profile_version,data_nature,source_values,payload_hash,evidence_id,managed_properties,observed_at,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (tenant,binding_id,p['source_id'],table['table'],_hash(item['key']),_json(item['key']),_json(_key_contract(table)),entity['entity_key'],_json(table['type_ref']),revision,entity['revision'],p['profile_id'],p['version'],p.get('data_nature','unspecified'),_json(item['values']),item['digest'],evidence['id'],_json(managed),snapshot,now,now))
            item['status'] = 'created'
        item['binding'] = self._binding(tx,tenant,p['source_id'],table['table'],item['key'])
        self._link_evidence(tx,tenant,[evidence['id']],'entity',entity['entity_key'])
        self._link_evidence(tx,tenant,[evidence['id']],'source_binding',item['binding']['id'])
        tx.execute('INSERT INTO source_binding_revisions(tenant_id,binding_id,revision,batch_id,source_id,profile_id,profile_version,source_values,entity_snapshot,evidence_id,payload_hash,observed_at,recorded_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (tenant,item['binding']['id'],revision,p['batch_id'],p['source_id'],p['profile_id'],p['version'],_json(item['values']),_json(entity),evidence['id'],item['digest'],snapshot,now,str(actor['id'])))

    def _sync_relations(self, tx, tenant, actor, p, item, tables, counts):
        if item['unchanged']:
            return
        binding, values = item['binding'], item['values']
        desired = {}
        for relation in item['table']['relations']:
            present = [f in values for f in relation['fields']]
            raw = [values.get(f) for f in relation['fields']]
            if not all(present) or any(x is None for x in raw):
                if not relation.get('nullable',True):
                    raise DomainError(422, 'source_reference_required', '缺少必填来源关系字段', {'relation_key':relation['relation_key'],'fields':relation['fields']})
                # Partial composite keys are never silently treated as null.
                if any(present) and not all(present) or any(x is None for x in raw) and not all(x is None for x in raw):
                    raise DomainError(422, 'partial_source_reference', '复合来源关系必须整体提供或整体置空', {'relation_key':relation['relation_key']})
                continue
            target_table = tables[relation['target_table']]
            target_key = _key(target_table, dict(zip(relation['target_fields'],raw)))
            target = self._binding(tx,tenant,p['source_id'],relation['target_table'],target_key)
            if not target:
                raise DomainError(422, 'unresolved_source_reference', '引用对象尚未导入；同批加入目标或先导入目标，再重试整批',
                                  {'relation_key':relation['relation_key'],'target_table':relation['target_table'],'target_key':target_key})
            if target['key_contract'] != _key_contract(target_table) or target['type_ref'] != target_table['type_ref']:
                raise DomainError(409, 'source_reference_contract_conflict', '被引用对象的已绑定身份与当前来源映射不兼容')
            desired[relation['relation_key']] = (relation,target,_hash({'predicate_ref':relation['predicate_ref'],'target_binding_id':target['id']}))
        active = [_row(r) for r in tx.execute('SELECT * FROM source_relation_links WHERE tenant_id=%s AND binding_id=%s AND closed_at IS NULL',
                                             (tenant,binding['id'])).fetchall()]
        unchanged = set()
        snapshot = _time(p['observed_at'])
        for link in active:
            wanted = desired.get(link['relation_key'])
            if wanted and wanted[2] == link['mapping_hash']:
                unchanged.add(link['relation_key'])
                continue
            tx.execute('UPDATE relations SET valid_to=%s,revision=revision+1 WHERE tenant_id=%s AND id=%s',
                       (snapshot,tenant,link['relation_id']))
            tx.execute('UPDATE source_relation_links SET closed_at=%s,ended_revision=%s WHERE tenant_id=%s AND id=%s',
                       (snapshot,binding['revision'],tenant,link['id']))
            counts['relations_closed'] += 1
        for key, (relation,target,mapping_hash) in desired.items():
            if key in unchanged:
                continue
            ref = relation['predicate_ref']
            created = self._do_create_relation(tx,tenant,actor,{
                'subject_key':binding['entity_key'],'object_key':target['entity_key'],
                'package_id':ref['package_id'],'package_version':ref['version'],'predicate_id':ref['predicate_id'],
                'status':'candidate','valid_from':snapshot,'evidence_ids':[binding['evidence_id']],
                'qualifiers':{'source_id':p['source_id'],'source_binding_id':binding['id'],'source_revision':binding['revision'],
                              'relation_key':key,'source_snapshot_at':snapshot,'temporal_basis':'source_snapshot_not_business_event'}})
            tx.execute('INSERT INTO source_relation_links(tenant_id,id,binding_id,relation_key,relation_id,target_binding_id,mapping_hash,started_revision,opened_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (tenant,_id(),binding['id'],key,created['id'],target['id'],mapping_hash,binding['revision'],snapshot))
            counts['relations_created'] += 1

    def _do_import_source_batch(self, tx, tenant, actor, p):
        _validate('import_source_batch', p)
        profile = self._profile(tx,tenant,p['source_id'],p['profile_id'],p['version'])
        previous = _row(tx.execute('SELECT * FROM source_batches WHERE tenant_id=%s AND source_id=%s AND batch_id=%s',
                                  (tenant,p['source_id'],p['batch_id'])).fetchone())
        if previous:
            if previous['payload_hash'] != _hash(p):
                raise DomainError(409, 'source_batch_conflict', '批次标识已用于不同内容，请使用新的批次标识')
            return previous['response']
        snapshot = _time(p['observed_at'])
        if datetime.fromisoformat(snapshot) > datetime.now(timezone.utc):
            raise DomainError(422, 'future_source_snapshot', '来源快照时间不能晚于当前时间；预报的未来有效时间应保存在来源字段')
        tables = {t['table']:t for t in profile['definition']['tables']}
        prepared, seen, errors = [], set(), []
        for index, record in enumerate(p['records']):
            try:
                if record['table'] not in tables:
                    raise DomainError(422, 'unmapped_source_table', '来源表未在当前版本映射中启用')
                item = self._prepare_record(tx,tenant,p,tables[record['table']],record,index)
                token = (record['table'],_hash(item['key']))
                if token in seen:
                    raise DomainError(422, 'duplicate_source_record', '同批包含重复来源身份')
                seen.add(token)
                prepared.append(item)
            except DomainError as exc:
                errors.append({'index':index,'table':record['table'],'code':exc.code,'message':exc.message,'details':exc.details,'status':exc.status})
        if errors:
            status = 409 if any(e['status'] == 409 for e in errors) else 422
            raise DomainError(status, 'source_batch_validation_failed', '来源批次校验失败，整批未写入', errors)
        if sum(len(_json(x['values']).encode('utf-8')) for x in prepared) > 2*1024*1024:
            raise DomainError(413, 'source_batch_too_large', '合并已有字段后的批次快照超过 2 MiB')
        counts = {'created':0,'updated':0,'unchanged':0,'relations_created':0,'relations_closed':0}
        # Stage 1 creates all target identities, so record order and cyclic FKs
        # do not create false missing-reference failures inside this batch.
        for item in prepared:
            try:
                self._store_record(tx,tenant,actor,p,item)
                counts[item['status']] += 1
            except DomainError as exc:
                raise DomainError(exc.status,'source_batch_validation_failed','来源批次校验失败，整批未写入',
                                  [{'index':item['index'],'table':item['table']['table'],'code':exc.code,'message':exc.message,'details':exc.details}]) from exc
        for item in prepared:
            try:
                self._sync_relations(tx,tenant,actor,p,item,tables,counts)
            except DomainError as exc:
                raise DomainError(exc.status,'source_batch_validation_failed','来源关系校验失败，整批未写入',
                                  [{'index':item['index'],'table':item['table']['table'],'code':exc.code,'message':exc.message,'details':exc.details}]) from exc
        result = {'id':'urn:source-batch:'+quote(p['source_id'],safe='')+':'+quote(p['batch_id'],safe=''),
                  'source_id':p['source_id'],'profile_id':p['profile_id'],'version':p['version'],'batch_id':p['batch_id'],
                  'data_nature':p.get('data_nature','unspecified'),
                  'observed_at':snapshot,'status':'stored','counts':counts,'records':[],'revision':1}
        for item in prepared:
            binding = item['binding']
            result['records'].append({'table':item['table']['table'],'source_key':item['key'],'binding_id':binding['id'],
                                      'entity_key':binding['entity_key'],'revision':binding['revision'],'entity_revision':binding['entity_revision'],
                                      'status':item['status'],'deferred_fields':item['deferred_fields'],'evidence_id':binding['evidence_id']})
        tx.execute('INSERT INTO source_batches(tenant_id,source_id,batch_id,profile_id,profile_version,payload_hash,observed_at,response,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (tenant,p['source_id'],p['batch_id'],p['profile_id'],p['version'],_hash(p),snapshot,_json(result),_now(),str(actor['id'])))
        return result

    @staticmethod
    def _preview_result(result):
        result = deepcopy(result)
        result['read_only'] = True
        result['would_store'] = True
        if 'batch' in result:
            result['batch'] = SourceMappingService._preview_result(result['batch'])
        if 'profile' in result:
            result['profile'] = {k:result['profile'][k] for k in ('source_id','profile_id','version','content_hash')}
        for row in result.get('records',[]):
            # Even existing IDs are hidden here: a preview is a plan, never a
            # durable identity receipt that another operation may dereference.
            for key in ('binding_id','entity_key','evidence_id'):
                row.pop(key,None)
        return result

    def _preview(self, action, tenant, actor, p):
        self._guard(tenant,actor,_WRITE_ROLES)
        _validate(action,p)
        with self.db.transaction() as tx:
            tx.execute('SAVEPOINT source_preview')
            # Use the same tenant serialization as Service.mutate. A preview
            # cannot race a committed import and report a fictitious revision.
            tx.execute('INSERT INTO outbox_counters(tenant_id,next_sequence) VALUES (%s,%s) ON CONFLICT(tenant_id) DO NOTHING',(tenant,1))
            tx.execute('SELECT next_sequence FROM outbox_counters WHERE tenant_id=%s FOR UPDATE',(tenant,))
            try:
                operation = self._do_install_source_bundle if action == 'preview_source_bundle' else self._do_import_source_batch
                return self._preview_result(operation(tx,tenant,actor,p))
            finally:
                tx.execute('ROLLBACK TO SAVEPOINT source_preview')
                tx.execute('RELEASE SAVEPOINT source_preview')

    def preview_source_batch(self, tenant, actor, p):
        return self._preview('preview_source_batch',tenant,actor,p)

    def preview_source_bundle(self, tenant, actor, p):
        return self._preview('preview_source_bundle',tenant,actor,p)

    def _evidence_bundle(self, tx, tenant, p):
        bundle = super()._evidence_bundle(tx,tenant,p)
        # One source binding owns one generated entity (database UNIQUE key).
        # History is available through paged source_bindings, never expanded
        # without a budget inside an ordinary current-state evidence bundle.
        binding = _row(tx.execute('SELECT * FROM source_bindings WHERE tenant_id=%s AND entity_key=%s LIMIT 1',
                                 (tenant,bundle['identity']['entity_key'])).fetchone())
        bundle['source_snapshots'] = []
        if binding:
            history = _row(tx.execute('SELECT * FROM source_binding_revisions WHERE tenant_id=%s AND binding_id=%s AND revision=%s',
                                     (tenant,binding['id'],binding['revision'])).fetchone())
            evidence = self._evidence(tx,tenant,[binding['evidence_id']],active=False)[0]
            active = evidence['status'] == 'active'
            consistent = binding['entity_revision'] == bundle['identity']['revision'] and history is not None
            snapshot = {'binding_id':binding['id'],'source_id':binding['source_id'],'table':binding['source_table'],
                        'source_key':binding['source_key'],'revision':binding['revision'],'entity_revision':binding['entity_revision'],
                        'profile_ref':{'profile_id':binding['profile_id'],'version':binding['profile_version']},
                        'type_ref':binding['type_ref'],'observed_at':binding['observed_at'],
                        'recorded_at':history['recorded_at'] if history else None,'data_nature':binding['data_nature'],
                        'information_nature':'source_snapshot','truth_status':'unreviewed_source_record',
                        'attributes':history['entity_snapshot']['attributes'] if history else {},
                        'evidence_ids':[binding['evidence_id']],'evidence_status':evidence['status'],
                        'eligible_for_reference':active and consistent,
                        'usable_for_inference':False,'adopted_as_premise':False,
                        'note':'来源属性仅说明该来源曾这样记录；不是观测或已采纳断言。推理层必须显式选择前提并检查数据性质与证据状态。'}
            bundle['source_snapshots'].append(snapshot)
            if evidence['id'] not in {x['id'] for x in bundle['evidence']}:
                bundle['evidence'].append(evidence)
            bundle['gaps'] = [x for x in bundle['gaps'] if x['code'] != 'no_records']
            if not active and not any(x.get('evidence_id') == evidence['id'] for x in bundle['gaps']):
                bundle['gaps'].append({'code':'source_evidence_withdrawn','evidence_id':evidence['id']})
            if not consistent:
                bundle['gaps'].append({'code':'source_entity_revision_mismatch','binding_id':binding['id']})
            if binding['data_nature'] != 'production':
                bundle['gaps'].append({'code':'source_not_declared_production','data_nature':binding['data_nature'],'binding_id':binding['id']})
            bundle['gaps'].append({'code':'source_snapshot_not_adopted','binding_id':binding['id']})
            bundle['retrieval_manifest']['source_binding_refs'] = [{'binding_id':binding['id'],'revision':binding['revision'],'evidence_id':binding['evidence_id']}]
            bundle['retrieval_manifest']['source_snapshot_limit'] = 1
        bundle.pop('content_hash',None)
        bundle['content_hash'] = _hash(bundle)
        return bundle

    def query(self, action, tenant, actor, params=None):
        if action == 'preview_source_batch':
            return self.preview_source_batch(tenant,actor,params or {})
        if action == 'preview_source_bundle':
            return self.preview_source_bundle(tenant,actor,params or {})
        if action not in {'source_profiles','source_bindings','source_batches'}:
            return super().query(action,tenant,actor,params)
        self._guard(tenant,actor,self.READ_ROLES)
        p = {} if params is None else params
        if not isinstance(p,dict):
            raise DomainError(422,'invalid_query','查询参数必须为对象')
        fields = {'source_profiles':{'source_id':'source_id','profile_id':'profile_id','version':'version'},
                  'source_bindings':{'source_id':'source_id','table':'source_table','profile_id':'profile_id','version':'profile_version','entity_key':'entity_key','binding_id':'id'},
                  'source_batches':{'source_id':'source_id','profile_id':'profile_id','version':'profile_version','batch_id':'batch_id'}}[action]
        paging = {'limit','offset'}
        if action == 'source_bindings':
            paging |= {'history_limit','history_offset','relationship_limit','relationship_offset'}
        options = {'projection'} if action == 'source_bindings' else set()
        if set(p) - (set(fields)|paging|options):
            raise DomainError(422,'unsupported_query','查询包含未支持参数', sorted(set(p)-(set(fields)|paging|options)))
        if p.get('projection','full') not in {'full','identity'}:
            raise DomainError(422,'invalid_projection','projection 只能为 full 或 identity')
        identity_only = action == 'source_bindings' and p.get('projection') == 'identity'
        if identity_only and set(p)&(paging-{'limit','offset'}):
            raise DomainError(422,'projection_history_conflict','identity 投影不返回记录历史，请单独查询 full 投影')
        if action == 'source_bindings' and set(p)&(paging-{'limit','offset'}) and not (p.get('binding_id') or p.get('entity_key')):
            raise DomainError(422,'invalid_query','历史分页需要同时指定 binding_id 或 entity_key')
        p = dict(p)
        for key in paging:
            if key not in p:
                continue
            value = p[key]
            if isinstance(value,bool) or not isinstance(value,(str,int)) or len(str(value)) > 19 or not re.fullmatch(r'[0-9]+',str(value)):
                raise DomainError(422,'invalid_pagination','分页参数必须为有界非负整数',{'field':key})
            number = int(value)
            maximum = (1000 if key == 'limit' else 100) if key.endswith('limit') else 9223372036854775807
            minimum = 1 if key.endswith('limit') else 0
            if not minimum <= number <= maximum:
                raise DomainError(422,'invalid_pagination','分页参数超出允许范围',{'field':key,'minimum':minimum,'maximum':maximum})
            p[key] = number
        columns = 'id,source_id,source_table,source_key,entity_key,type_ref,key_contract,revision,entity_revision,profile_id,profile_version,data_nature,observed_at,created_at,updated_at' if identity_only else '*'
        sql, args = 'SELECT '+columns+' FROM '+action+' WHERE tenant_id=%s', [tenant]
        for key, column in fields.items():
            if key in p:
                if not isinstance(p[key],str) or not p[key] or len(p[key])>500:
                    raise DomainError(422,'invalid_query','查询筛选值必须为有界字符串')
                value = _uuid(p[key],key) if key in {'binding_id','entity_key'} else p[key]
                sql += ' AND '+column+'=%s'
                args.append(value)
        sql += ' ORDER BY created_at,'+{'source_profiles':'source_id,profile_id,version','source_bindings':'id','source_batches':'source_id,batch_id'}[action]
        with self.db.transaction() as tx:
            page = self._list(tx,sql,args,p)
            page['items'] = [_row(row) for row in page['items']]
            if action == 'source_bindings':
                for binding in page['items']:
                    binding['table'] = binding['source_table']
            if action == 'source_bindings' and not identity_only and (p.get('binding_id') or p.get('entity_key')):
                for binding in page['items']:
                    for kind,table,order in [('history','source_binding_revisions','revision'),('relationship','source_relation_links','opened_at,id')]:
                        params = {'limit':p.get(kind+'_limit',100),'offset':p.get(kind+'_offset',0)}
                        if isinstance(params['limit'],bool) or not str(params['limit']).isdigit() or not 1 <= int(params['limit']) <= 100:
                            raise DomainError(422,'invalid_history_limit','历史分页大小必须为 1 至 100')
                        history = self._list(tx,'SELECT * FROM '+table+' WHERE tenant_id=%s AND binding_id=%s ORDER BY '+order,[tenant,binding['id']],params)
                        name = 'history' if kind == 'history' else 'relationships'
                        binding[name] = [_row(row) for row in history['items']]
                        binding[name+'_page'] = {k:v for k,v in history.items() if k != 'items'}
            return page
