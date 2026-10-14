"""Database ontology registry: exact identity, deterministic validation, no AI judgment."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from .field_service import FieldService
from .service import DomainError, _now, _json, _text, _time, _unpack, _hash, _id, _uuid

CORE_SCHEMAS = json.loads((Path(__file__).resolve().parents[1] / 'contracts' / 'ontology-core-schemas.json').read_text(encoding='utf-8'))
BUILTINS = {
    'gate.state': {'property_id':'gate.state','label':'闸门状态','value_type':'enum','unit':'1','enum_values':['open','closed','partial','unknown'],'usage':'observation','cardinality':'single'},
    'gate.position_pct': {'property_id':'gate.position_pct','label':'闸门开度','value_type':'decimal','unit':'%','minimum':0,'maximum':100,'usage':'observation','cardinality':'single'},
}

def validate_core(action, payload):
    if action not in CORE_SCHEMAS: return
    errors=list(Draft202012Validator(CORE_SCHEMAS[action],format_checker=FormatChecker()).iter_errors(payload))
    if errors:
        raise DomainError(422,'schema_validation_failed','输入不符合本体契约',[{'path':list(e.path),'message':e.message} for e in errors[:10]])

def _decode(value):
    return json.loads(value) if isinstance(value,str) else value

def _dt(value):
    return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(timezone.utc)

def _active(assignment, at):
    return _dt(assignment['valid_from']) <= _dt(at) and (not assignment.get('valid_to') or _dt(at) < _dt(assignment['valid_to']))

def validate_property_value(definition, value, usage=None):
    """Validate only; do not silently coerce units, types, missing values or names."""
    if usage and definition['usage'] != usage:
        raise DomainError(422,'property_usage_mismatch','属性用途与记录类型不对应')
    if not isinstance(value,dict) or 'value' not in value or value['value'] is None:
        raise DomainError(422,'invalid_property_value','属性值必须包含非空 value')
    if set(value)-{'value','unit','context','scope'}:
        raise DomainError(422,'invalid_property_value','属性值包含未声明字段')
    if value.get('unit') != definition.get('unit'):
        raise DomainError(422,'property_unit_mismatch','单位必须与属性定义完全一致；请在来源映射中显式转换',{'expected':definition.get('unit'),'actual':value.get('unit')})
    values=value['value']
    if definition.get('cardinality','single')=='many':
        if not isinstance(values,list) or not 1<=len(values)<=100:
            raise DomainError(422,'property_cardinality','多值属性需要 1 至 100 个值')
    else:
        if isinstance(values,list): raise DomainError(422,'property_cardinality','单值属性不能接收数组')
        values=[values]
    kind=definition['value_type']
    for item in values:
        valid=False; number=None
        if kind=='decimal':
            if not isinstance(item,bool) and isinstance(item,(str,int,float,Decimal)):
                try:
                    number=Decimal(str(item)); valid=number.is_finite()
                except InvalidOperation: pass
        elif kind=='integer': valid=isinstance(item,int) and not isinstance(item,bool); number=Decimal(item) if valid else None
        elif kind=='boolean': valid=isinstance(item,bool)
        elif kind=='string': valid=isinstance(item,str) and len(item)<=10000
        elif kind=='enum': valid=isinstance(item,str) and item in definition['enum_values']
        elif kind=='datetime':
            if isinstance(item,str):
                try: _time(item,'value');valid=True
                except DomainError: pass
        if not valid: raise DomainError(422,'property_value_type','属性值不符合已登记类型或枚举',{'property_id':definition['property_id'],'expected':kind})
        if number is not None:
            if 'minimum' in definition and number<Decimal(str(definition['minimum'])) or 'maximum' in definition and number>Decimal(str(definition['maximum'])):
                raise DomainError(422,'property_value_range','属性值超出已声明的数据约束')
    return value

class OntologyService(FieldService):
    ACTION_ROLES=dict(FieldService.ACTION_ROLES,update_package_labels={'admin','ontology_admin'})
    input_schemas={**json.loads((Path(__file__).resolve().parents[1] / 'contracts' / 'input-schemas.json').read_text(encoding='utf-8')),**CORE_SCHEMAS}

    def mutate(self,action,tenant,actor,payload,idempotency_key):
        validate_core(action,payload)
        return super().mutate(action,tenant,actor,payload,idempotency_key)

    def _package_view(self,tx,tenant,row):
        row=_unpack(row); definition=row['definition']
        display=tx.execute('SELECT * FROM ontology_display WHERE tenant_id=%s AND package_id=%s AND package_version=%s',(tenant,row['package_id'],row['version'])).fetchone()
        labels=_decode(display['labels']) if display else {}
        row['label']=labels.get('label',definition.get('label',row['package_id']))
        row['description']=labels.get('description',definition.get('description',''))
        row['display_revision']=int(display['revision']) if display else 0
        row['validation_profile']='registered_properties' if 'properties' in definition else 'legacy_unvalidated'
        for kind,key in [('types','type_labels'),('properties','property_labels'),('predicates','predicate_labels')]:
            idkey={'types':'type_id','properties':'property_id','predicates':'predicate_id'}[kind]
            items=deepcopy(definition.get(kind,[]))
            for item in items:
                item['label']=labels.get(key,{}).get(item[idkey],item.get('label',item[idkey]))
                if kind=='properties':
                    item.setdefault('required',False);item.setdefault('cardinality','single')
            row[kind]=items
        row['display_labels']=labels
        return row

    def _get_package(self,tx,tenant,package_id,version):
        row=tx.execute('SELECT * FROM ontology_packages WHERE tenant_id=%s AND package_id=%s AND version=%s',(tenant,package_id,version)).fetchone()
        if not row: raise DomainError(404,'package_not_found','当前租户中没有这个本体版本')
        return self._package_view(tx,tenant,row)

    def _do_register_package(self,tx,tenant,actor,p):
        validate_core('register_package',p)
        types={t['type_id']:t for t in p['types']}
        if len(types)!=len(p['types']): raise DomainError(422,'duplicate_type','类标识不能重复')
        props=p.get('properties',[]); ids=set()
        for prop in props:
            if prop['property_id'] in ids: raise DomainError(422,'duplicate_property','属性标识不能重复')
            ids.add(prop['property_id'])
            if not set(prop['applies_to'])<=set(types): raise DomainError(422,'unknown_property_class','属性适用类必须在该本体版本中定义')
            if prop['value_type']=='enum' and not prop.get('enum_values'): raise DomainError(422,'enum_values_required','枚举属性必须定义可选值')
            if prop['value_type']!='enum' and 'enum_values' in prop: raise DomainError(422,'unexpected_enum','只有枚举属性可以声明枚举值')
            if prop.get('required') and prop['usage']!='attribute': raise DomainError(422,'required_usage','必填约束仅用于对象属性，不能要求每次提交所有观测')
            if ('minimum' in prop or 'maximum' in prop) and prop['value_type'] not in {'decimal','integer'}: raise DomainError(422,'numeric_constraint','数值范围仅可用于数值属性')
            if prop.get('minimum',float('-inf'))>prop.get('maximum',float('inf')): raise DomainError(422,'invalid_range','最小值不能大于最大值')
        predicate_ids=set()
        for predicate in p.get('predicates',[]):
            if predicate['predicate_id'] in predicate_ids: raise DomainError(422,'duplicate_predicate','关系标识不能重复')
            predicate_ids.add(predicate['predicate_id'])
            for semantic,identity in [('subject_semantic_types','subject_types'),('object_semantic_types','object_types')]:
                for type_id in predicate.get(semantic,[]):
                    if type_id not in types: raise DomainError(422,'unknown_relation_class','关系端点类未在本体中定义')
                    if '*' not in predicate[identity] and types[type_id]['identity_type'] not in predicate[identity]: raise DomainError(422,'relation_class_identity','关系语义类与身份类型不兼容')
        prior=tx.execute('SELECT 1 FROM ontology_packages WHERE tenant_id=%s AND package_id=%s AND version=%s',(tenant,p['package_id'],p['version'])).fetchone()
        super()._do_register_package(tx,tenant,actor,p)
        if not prior:
            for prop in props:
                definition=dict(prop);definition.setdefault('required',False);definition.setdefault('cardinality','single')
                tx.execute('INSERT INTO ontology_properties(tenant_id,package_id,package_version,property_id,usage,definition) VALUES (%s,%s,%s,%s,%s,%s)',(tenant,p['package_id'],p['version'],prop['property_id'],prop['usage'],_json(definition)))
            labels={'label':p.get('label',p['package_id']),'description':p.get('description','')}
            tx.execute('INSERT INTO ontology_display(tenant_id,package_id,package_version,labels,revision,updated_at,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,p['package_id'],p['version'],_json(labels),1,_now(),str(actor['id'])))
        return self._get_package(tx,tenant,p['package_id'],p['version'])

    def _do_update_package_labels(self,tx,tenant,actor,p):
        validate_core('update_package_labels',p)
        package=self._get_package(tx,tenant,p['package_id'],p['version'])
        if p['expected_revision']!=package['display_revision']: raise DomainError(409,'display_revision_conflict','名称已被修改，请刷新后重试',{'current_revision':package['display_revision']})
        changed=set(p)-{'package_id','version','expected_revision'}
        if not changed: raise DomainError(422,'empty_label_update','请提供至少一项名称或说明')
        labels=deepcopy(package['display_labels'])
        for key in changed:
            if key.endswith('_labels'):
                kind={'type_labels':'types','property_labels':'properties','predicate_labels':'predicates'}[key]
                idkey={'types':'type_id','properties':'property_id','predicates':'predicate_id'}[kind]
                if not set(p[key])<={x[idkey] for x in package[kind]}: raise DomainError(422,'unknown_label_target','名称变更包含不存在的类、属性或关系')
                labels.setdefault(key,{}).update(p[key])
            else: labels[key]=p[key]
        revision=package['display_revision']+1
        if package['display_revision']==0:
            tx.execute('INSERT INTO ontology_display(tenant_id,package_id,package_version,labels,revision,updated_at,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,p['package_id'],p['version'],_json(labels),revision,_now(),str(actor['id'])))
        else:
            tx.execute('UPDATE ontology_display SET labels=%s,revision=%s,updated_at=%s,updated_by=%s WHERE tenant_id=%s AND package_id=%s AND package_version=%s',(_json(labels),revision,_now(),str(actor['id']),tenant,p['package_id'],p['version']))
        tx.execute('INSERT INTO audit_log(tenant_id,id,actor_id,action,target_id,details,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),str(actor['id']),'ontology.display.changed',p['package_id'],_json({'version':p['version'],'previous_revision':package['display_revision'],'revision':revision,'before':package['display_labels'],'after':labels}),_now()))
        result=self._get_package(tx,tenant,p['package_id'],p['version']);result['revision']=revision
        return result

    def _property_candidates(self,tx,tenant,entity,at,property_id=None,usage=None):
        candidates={}
        for assignment in entity['semantic_types']:
            if not _active(assignment,at): continue
            rows=tx.execute('SELECT * FROM ontology_properties WHERE tenant_id=%s AND package_id=%s AND package_version=%s',(tenant,assignment['package_id'],assignment['package_version'])).fetchall()
            for row in rows:
                definition=_decode(row['definition'])
                if assignment['type_id'] not in definition['applies_to'] or property_id and row['property_id']!=property_id or usage and definition['usage']!=usage: continue
                ref={'package_id':row['package_id'],'version':row['package_version'],'property_id':row['property_id']}
                candidates[tuple(ref.values())]=(ref,definition)
        return list(candidates.values())

    def resolve_property(self,tx,tenant,entity,property_id,reference,at,usage):
        candidates=self._property_candidates(tx,tenant,entity,at,property_id,usage)
        if reference:
            if reference.get('property_id')!=property_id: raise DomainError(422,'property_reference_mismatch','属性标识与版本引用不一致')
            candidates=[x for x in candidates if x[0]==reference]
        if len(candidates)!=1:
            raise DomainError(422,'needs_mapping','属性未对应到对象在该时点有效的唯一类定义，请先完成对象分类与来源映射',{'property_id':property_id,'candidate_refs':[x[0] for x in candidates]})
        return candidates[0]

    def _validation(self,tx,tenant,kind,record_id,status,reference=None,details=None):
        tx.execute('INSERT INTO semantic_validations(tenant_id,record_kind,record_id,validation_status,property_ref,details,validated_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,record_kind,record_id) DO UPDATE SET validation_status=excluded.validation_status,property_ref=excluded.property_ref,details=excluded.details,validated_at=excluded.validated_at',(tenant,kind,record_id,status,_json(reference) if reference else None,_json(details or {}),_now()))

    def _decorate_record(self,tx,tenant,kind,record):
        row=tx.execute('SELECT * FROM semantic_validations WHERE tenant_id=%s AND record_kind=%s AND record_id=%s',(tenant,kind,record.get('id') or record.get('entity_key'))).fetchone()
        record['validation_status']=row['validation_status'] if row else 'legacy_unvalidated'
        record['property_ref']=_decode(row['property_ref']) if row and row['property_ref'] else None
        return record

    def _entity(self,tx,tenant,key):
        return self._decorate_record(tx,tenant,'entity',super()._entity(tx,tenant,key))

    def _check_attributes(self,tx,tenant,entity,at):
        props=self._property_candidates(tx,tenant,entity,at,usage='attribute'); by_id={}
        for ref,definition in props: by_id.setdefault(ref['property_id'],[]).append(definition)
        attributes=entity.get('attributes',{})
        for key,value in attributes.items():
            if key=='synthetic' and isinstance(value,bool): continue
            if key not in by_id: raise DomainError(422,'unknown_attribute','属性未在对象有效语义类中声明',{'attribute':key})
            if len(by_id[key])!=1: raise DomainError(422,'ambiguous_attribute','多个本体版本定义同名属性，不能自动选择',{'attribute':key})
            definition=by_id[key][0]
            validate_property_value(definition,value if isinstance(value,dict) else {'value':value},'attribute')
        for key,definitions in by_id.items():
            if any(x.get('required') for x in definitions) and key not in attributes: raise DomainError(422,'required_attribute','缺少已声明的必填属性',{'attribute':key})

    def _do_create_entity(self,tx,tenant,actor,p):
        validate_core('create_entity',p)
        identity,name=_text(p,'entity_type'),_text(p,'name')
        if identity not in self.CORE_TYPES and not tx.execute('SELECT 1 FROM ontology_types WHERE tenant_id=%s AND identity_type=%s',(tenant,identity)).fetchone():
            raise DomainError(422,'unknown_identity_type','先登记扩展身份类型')
        now=_now()
        if p.get('semantic_types'):
            assignments=[dict(a,package_version=a['version'],valid_from=a.get('valid_from',now),valid_to=a.get('valid_to')) for a in p['semantic_types']]
            self._check_attributes(tx,tenant,{'semantic_types':assignments,'attributes':p.get('attrs',{})},now)
        key=_uuid(p['entity_key']) if p.get('entity_key') else _id()
        entity_id=_uuid(p['entity_id']) if p.get('entity_id') else _id()
        tx.execute('INSERT INTO entities(tenant_id,entity_key,entity_type,entity_id,name,attributes,revision,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,key,identity,entity_id,name,_json(p.get('attrs',{})),1,now,str(actor['id'])))
        for assignment in p.get('semantic_types',[]):
            # Validate the complete declared class set above, not each incomplete prefix.
            super()._do_assign_type(tx,tenant,actor,dict(assignment,entity_key=key))
        self._validation(tx,tenant,'entity',key,'validated' if p.get('semantic_types') else 'unvalidated')
        return self._entity(tx,tenant,key)

    def _do_assign_type(self,tx,tenant,actor,p):
        validate_core('assign_type',p)
        result=super()._do_assign_type(tx,tenant,actor,p)
        self._check_attributes(tx,tenant,self._entity(tx,tenant,p['entity_key']),p.get('valid_from',_now()))
        self._validation(tx,tenant,'entity',p['entity_key'],'validated')
        return result

    def _do_create_observation(self,tx,tenant,actor,p):
        validate_core('create_observation',p)
        entity=self._entity(tx,tenant,p['subject_key']); at=_time(p['observed_at'],'observed_at')
        if _dt(at)>datetime.now(timezone.utc)+timedelta(minutes=5):
            raise DomainError(422,'future_observation','观测不能记录尚未发生的读数；未来预报请登记 forecast 候选断言')
        reference=p.get('property_ref'); status='validated'
        if p['property_id'] in BUILTINS and not reference:
            gate=tx.execute('SELECT id FROM device_registrations WHERE tenant_id=%s AND device_entity_key=%s AND device_kind=%s',(tenant,entity['entity_key'],'gate')).fetchone()
            if not gate: raise DomainError(422,'builtin_device_required','内置闸门属性仅用于已登记的闸门设备')
            definition=BUILTINS[p['property_id']];reference={'package_id':'builtin.device','version':'1.0.0','property_id':p['property_id']};status='builtin_validated'
        else:
            reference,definition=self.resolve_property(tx,tenant,entity,p['property_id'],reference,at,'observation')
        validate_property_value(definition,p['value'],'observation')
        result=super()._do_create_observation(tx,tenant,actor,p)
        self._validation(tx,tenant,'observation',result['id'],status,reference)
        return self._decorate_record(tx,tenant,'observation',result)

    def _do_create_assertion(self,tx,tenant,actor,p):
        validate_core('create_assertion',p);reference=p.get('property_ref')
        if reference:
            entity=self._entity(tx,tenant,p['subject_key'])
            reference,definition=self.resolve_property(tx,tenant,entity,p['predicate_id'],reference,_now(),'assertion')
            validate_property_value(definition,p.get('value'),'assertion')
        result=super()._do_create_assertion(tx,tenant,actor,p)
        self._validation(tx,tenant,'assertion',result['id'],'validated' if reference else 'unvalidated',reference)
        return self._decorate_record(tx,tenant,'assertion',result)

    def _do_review_assertion(self,tx,tenant,actor,p):
        if p.get('status')=='accepted':
            row=tx.execute('SELECT validation_status FROM semantic_validations WHERE tenant_id=%s AND record_kind=%s AND record_id=%s',(tenant,'assertion',_uuid(p.get('assertion_id'),'assertion_id'))).fetchone()
            if not row or row['validation_status']!='validated': raise DomainError(422,'assertion_mapping_required','采纳前必须提供已校验的属性引用；旧记录保留原状态')
        return self._decorate_record(tx,tenant,'assertion',super()._do_review_assertion(tx,tenant,actor,p))

    def _check_relation_semantics(self,tx,tenant,p):
        package=self._get_package(tx,tenant,p.get('package_id'),p.get('package_version'))
        definition=next((x for x in package['predicates'] if x['predicate_id']==p.get('predicate_id')),None)
        if definition:
            at=_time(p.get('valid_from'),'valid_from'); end=_time(p.get('valid_to'),'valid_to',True)
            for side in ('subject','object'):
                allowed=definition.get(side+'_semantic_types')
                if not allowed: continue
                entity=self._entity(tx,tenant,p.get(side+'_key'))
                matches=[a for a in entity['semantic_types'] if a['package_id']==package['package_id'] and a['package_version']==package['version'] and a['type_id'] in allowed and _active(a,at) and (not a.get('valid_to') or end and _dt(end)<=_dt(a['valid_to']))]
                if not matches: raise DomainError(422,'relation_semantic_type','关系端点必须在完整有效区间内具有该本体版本要求的类',{'endpoint':side,'allowed':allowed})

    def _do_create_relation(self,tx,tenant,actor,p):
        self._check_relation_semantics(tx,tenant,p)
        return super()._do_create_relation(tx,tenant,actor,p)

    def _do_review_relation(self,tx,tenant,actor,p):
        if p.get('status')=='accepted':
            row=_unpack(tx.execute('SELECT * FROM relations WHERE tenant_id=%s AND id=%s',(tenant,_uuid(p.get('relation_id'),'relation_id'))).fetchone())
            if row: self._check_relation_semantics(tx,tenant,row)
        return super()._do_review_relation(tx,tenant,actor,p)

    def _evidence_bundle(self,tx,tenant,p):
        bundle=super()._evidence_bundle(tx,tenant,p)
        for kind,key in [('observation','observations'),('assertion','adopted_assertions'),('assertion','candidate_assertions')]:
            for record in bundle[key]:
                self._decorate_record(tx,tenant,kind,record)
                if kind=='observation':
                    record['usable_for_inference']=bool(record.get('usable_for_inference')) and record['validation_status'] in {'validated','builtin_validated'}
                    if record['validation_status']=='legacy_unvalidated': bundle['gaps'].append({'code':'observation_mapping_required','observation_id':record['id']})
        accepted=[]
        for record in bundle['adopted_assertions']:
            if record['validation_status']=='validated': accepted.append(record)
            else:
                bundle['candidate_assertions'].append(record)
                bundle['gaps'].append({'code':'assertion_mapping_required','assertion_id':record['id']})
        bundle['adopted_assertions']=accepted
        bundle.pop('content_hash',None);bundle['content_hash']=_hash(bundle)
        return bundle

    def query(self,action,tenant,actor,params=None):
        self._guard(tenant,actor,self.READ_ROLES);p=params or {}
        if not isinstance(p,dict): raise DomainError(422,'invalid_query','查询参数必须为对象')
        if action in {'packages','properties'}:
            allowed={'package_id','version','limit','offset'}|({'type_id','usage','entity_key','at'} if action=='properties' else set())
            if set(p)-allowed: raise DomainError(422,'invalid_query','查询包含未支持字段',sorted(set(p)-allowed))
            with self.db.transaction() as tx:
                if action=='packages':
                    sql='SELECT * FROM ontology_packages WHERE tenant_id=%s';args=[tenant]
                    for key in ('package_id','version'):
                        if p.get(key):sql+=' AND '+key+'=%s';args.append(p[key])
                    page=self._list(tx,sql+' ORDER BY package_id,version',args,p)
                    page['items']=[self._package_view(tx,tenant,row) for row in page['items']];return page
                if p.get('usage') and p['usage'] not in {'attribute','observation','assertion'}: raise DomainError(422,'invalid_usage','未知属性用途')
                sql='SELECT * FROM ontology_properties WHERE tenant_id=%s';args=[tenant]
                for source,column in [('package_id','package_id'),('version','package_version'),('usage','usage')]:
                    if p.get(source):sql+=' AND '+column+'=%s';args.append(p[source])
                # SQL handles identity filters; deterministic JSON class matching runs before pagination.
                rows=tx.execute(sql+' ORDER BY package_id,package_version,property_id LIMIT 10001',args).fetchall()
                if len(rows)>10000: raise DomainError(422,'property_query_budget','属性查询超过预算，请指定本体和版本后查询')
                entity=self._entity(tx,tenant,p['entity_key']) if p.get('entity_key') else None
                at=_time(p.get('at',_now()),'at');items=[];cache={}
                for row in rows:
                    prop=_decode(row['definition'])
                    if p.get('type_id') and p['type_id'] not in prop['applies_to']: continue
                    if entity and not any(a['package_id']==row['package_id'] and a['package_version']==row['package_version'] and a['type_id'] in prop['applies_to'] and _active(a,at) for a in entity['semantic_types']): continue
                    key=(row['package_id'],row['package_version'])
                    if key not in cache:cache[key]=self._get_package(tx,tenant,*key)
                    labels=cache[key]['display_labels'].get('property_labels',{})
                    items.append(dict(prop,label=labels.get(prop['property_id'],prop['label']),package_id=key[0],version=key[1]))
                limit=self._limit(p);offset=p.get('offset',0)
                if isinstance(offset,bool) or not str(offset).isdigit() or int(offset)>9223372036854775807: raise DomainError(422,'invalid_offset','offset必须是非负整数')
                offset=int(offset);more=len(items)>offset+limit
                return {'items':items[offset:offset+limit],'has_more':more,'truncated':more,'next_offset':offset+limit if more else None}
        result=super().query(action,tenant,actor,p)
        if action in {'observations','assertions','entities'}:
            kind={'observations':'observation','assertions':'assertion','entities':'entity'}[action]
            with self.db.transaction() as tx:
                for record in result['items']:self._decorate_record(tx,tenant,kind,record)
        return result


def seed_core_demo(service,base=None):
    """Add a distinct v0.3 synthetic demo; never rewrite the legacy seed payload."""
    tenant='demo-farm';actor={'id':'synthetic-core-seeder','roles':['admin']}
    def write(action,name,body):
        return service.mutate(action,tenant,actor,body,'demo-core-v03:'+name)
    package={'package_id':'agri.intake','version':'1.0.0','namespace':'https://example.org/agri/intake/','label':'农业基础数据本体（合成示例）',
      'description':'用于验证类、属性、单位及来源映射。显示名称可以修改，稳定标识不随名称变化；不代表梁子湖现场数据。',
      'types':[{'type_id':'intake:Field','identity_type':'field','label':'监测田块'}, {'type_id':'intake:Device','identity_type':'device','label':'监测设备'}],
      'properties':[
       {'property_id':'field.area','label':'面积','applies_to':['intake:Field'],'usage':'attribute','value_type':'decimal','unit':'ha','minimum':0},
       {'property_id':'field.code','label':'田块业务编号','applies_to':['intake:Field'],'usage':'attribute','value_type':'string'},
       {'property_id':'water.temperature','label':'水温','applies_to':['intake:Field'],'usage':'observation','value_type':'decimal','unit':'Cel'},
       {'property_id':'water.dissolved_oxygen','label':'溶解氧','applies_to':['intake:Field'],'usage':'observation','value_type':'decimal','unit':'mg/L'},
       {'property_id':'water.ph','label':'酸碱度','applies_to':['intake:Field'],'usage':'observation','value_type':'decimal','unit':'1','minimum':0,'maximum':14},
       {'property_id':'inspection.note','label':'外部检查陈述','applies_to':['intake:Field'],'usage':'assertion','value_type':'string'}],
      'predicates':[{'predicate_id':'intake:monitors','label':'监测','subject_types':['device'],'object_types':['field'],'subject_semantic_types':['intake:Device'],'object_semantic_types':['intake:Field'],'dimension':'observation'}]}
    registered=write('register_package','package',package)
    entity=write('create_entity','field',{'entity_type':'field','name':'映射试用田块（合成示例）','attrs':{'field.area':{'value':'1.2','unit':'ha'},'field.code':'DEMO-MAP-01','synthetic':True},'semantic_types':[{'package_id':'agri.intake','version':'1.0.0','type_id':'intake:Field','valid_from':'2020-01-01T00:00:00Z'}]})
    # Add display-only names to untouched legacy synthetic packages. Exact IDs,
    # namespaces, actor and zero display revision prevent overwriting user edits.
    legacy_labels={
        'agri.core':('https://example.org/agri/core/','农业通用本体（合成示例）'),
        'agri.rice-crayfish':('https://example.org/agri/rice-crayfish/','虾稻共作本体（合成示例）'),
        'agri.vegetable':('https://example.org/agri/vegetable/','蔬菜生产本体（合成示例）'),
        'agri.poultry':('https://example.org/agri/poultry/','禽蛋生产本体（合成示例）'),
    }
    for package_id,(namespace,label) in legacy_labels.items():
        page=service.query('packages',tenant,actor,{'package_id':package_id,'version':'1.0.0','limit':1})
        if not page['items']: continue
        old=page['items'][0]
        if old['namespace']!=namespace or old.get('created_by')!='synthetic-seeder' or old['display_revision']!=0: continue
        try:
            write('update_package_labels','legacy-display-'+package_id,{
                'package_id':package_id,'version':'1.0.0','expected_revision':0,'label':label,
                'description':'历史合成示例，仅用于理解农业类和关系；未登记完整属性约束，不代表梁子湖现场数据。请复制为新版本补充定义，或修改显示名称。'})
        except DomainError as exc:
            # A concurrent administrator rename wins; startup must not undo it.
            if exc.code!='display_revision_conflict': raise
    return {'package_id':registered['package_id'],'version':registered['version'],'field_key':entity['entity_key'],'synthetic':True}
