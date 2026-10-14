"""Explicit intake classification, deterministic mapping and durable receipts.
No network calls, image recognition, truth scoring or agricultural decisions.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import re
from jsonschema import Draft202012Validator, FormatChecker
from .ontology_core import OntologyService, CORE_SCHEMAS
from .service import DomainError, _hash, _id, _json, _now, _text, _time, _unpack, _uuid

INTAKE_SCHEMAS = json.loads((Path(__file__).resolve().parents[1]/'contracts'/'intake-core-schemas.json').read_text(encoding='utf-8'))
KINDS = {'entity':'create_entity','observation':'create_observation','assertion':'create_assertion','event':'create_event','relationship':'create_relation','evidence':'create_evidence'}
CATEGORIES = {'device','manual','external_system','model'}
JSON_COLUMNS = {'raw_envelope','issues','normalized_payload','result'}

def _row(row):
    row = _unpack(row)
    if row:
        for key in JSON_COLUMNS:
            if isinstance(row.get(key), str): row[key] = json.loads(row[key])
    return row

def _validate(name, payload):
    try:
        if len(_json(payload).encode('utf-8'))>2*1024*1024:raise DomainError(413,'intake_too_large','结构化接入信封超过 2 MiB')
    except (TypeError,ValueError):raise DomainError(422,'invalid_json','输入必须为有限 JSON 值')
    errors=list(Draft202012Validator(INTAKE_SCHEMAS[name],format_checker=FormatChecker()).iter_errors(payload))
    if errors:
        raise DomainError(422,'schema_validation_failed','接入参数不符合契约',[{'path':list(e.path),'message':e.message} for e in errors[:20]])

def _parts(pointer):
    if not isinstance(pointer,str) or not pointer.startswith('/') or len(pointer)>500:
        raise DomainError(422,'invalid_mapping_path','字段路径必须采用 JSON Pointer，例如 /temperature')
    tokens=pointer[1:].split('/')
    if len(tokens)>8 or any(re.search(r'~(?![01])',t) for t in tokens):
        raise DomainError(422,'invalid_mapping_path','字段路径过深或转义不合法')
    return [t.replace('~1','/').replace('~0','~') for t in tokens]

def _read(payload,pointer):
    value=payload
    for part in _parts(pointer):
        if isinstance(value,dict) and part in value:value=value[part]
        elif isinstance(value,list) and re.fullmatch(r'0|[1-9][0-9]*',part) and int(part)<len(value):value=value[int(part)]
        else:raise DomainError(422,'missing_source_field','来源字段不存在',{'source_path':pointer})
    return deepcopy(value)

def _write(payload,pointer,value):
    tokens=_parts(pointer); obj=payload
    for part in tokens[:-1]:
        if part not in obj:obj[part]={}
        if not isinstance(obj[part],dict):raise DomainError(422,'mapping_path_collision','目标路径与已有值冲突',{'target_path':pointer})
        obj=obj[part]
    obj[tokens[-1]]=value

def _number(value):
    if isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)):
        raise DomainError(422,'invalid_decimal_mapping','十进制转换只接受明确数值')
    try:number=Decimal(str(value))
    except InvalidOperation:raise DomainError(422,'invalid_decimal_mapping','来源值不能转换为十进制数')
    if not number.is_finite() or len(number.as_tuple().digits)>30 or abs(number.as_tuple().exponent)>12 or abs(number)>Decimal('1e30'):
        raise DomainError(422,'invalid_decimal_mapping','十进制值超出有限精度范围')
    return number

class IntakeService(OntologyService):
    ACTION_ROLES={**OntologyService.ACTION_ROLES,
        'register_mapping':{'admin','ontology_admin'},
        'receive_intake':{'admin','operator','reviewer','ontology_admin'},
        'retry_intake':{'admin','operator','reviewer','ontology_admin'}}

    def _mapping(self,tx,tenant,key,version):
        return _row(tx.execute('SELECT * FROM intake_mappings WHERE tenant_id=%s AND mapping_id=%s AND version=%s',(tenant,key,version)).fetchone())

    def _do_register_mapping(self,tx,tenant,actor,p):
        _validate('register_mapping',p)
        if KINDS[p['record_kind']]!=p['target_action']:
            raise DomainError(422,'mapping_kind_mismatch','记录类型与目标写入操作不对应')
        if p['mode']=='identity' and p.get('field_rules'):
            raise DomainError(422,'identity_mapping_rules','标准载荷映射不能同时声明字段转换')
        if p['mode']=='fields' and not p.get('field_rules'):
            raise DomainError(422,'mapping_rules_required','字段映射至少需要一条转换规则')
        paths=[]
        for rule in p.get('field_rules',[]):
            _parts(rule['source_path']); tokens=_parts(rule['target_path'])
            if tokens[0] in {'evidence_ids','status','origin'}:
                raise DomainError(422,'reserved_mapping_target','证据、采纳状态和信息性质不能由任意来源字段覆盖')
            if 'unit' in rule and tokens!=['value','value']:
                raise DomainError(422,'mapping_unit_target','unit 只能用于 /value/value 映射')
            writes=[tokens]+([['value','unit']] if 'unit' in rule else [])
            for target in writes:
                if any(target[:len(old)]==old or old[:len(target)]==target for old in paths):
                    raise DomainError(422,'mapping_path_collision','同一映射不能重复或交叉写入目标路径')
                paths.append(target)
            for name in ('scale','offset'):
                if name in rule:_number(rule[name])
            if ('scale' in rule or 'offset' in rule) and rule.get('value_type','decimal')!='decimal':
                raise DomainError(422,'mapping_conversion_conflict','缩放与偏移只适用于十进制转换')
            if rule.get('enum_map') and any(k in rule for k in ('scale','offset','value_type')):
                raise DomainError(422,'mapping_conversion_conflict','枚举映射不能与其他值转换混用')
            if rule.get('source_unit_path'):_parts(rule['source_unit_path'])
        if p.get('subject_key'):self._entity(tx,tenant,p['subject_key'])
        digest=_hash(p);existing=self._mapping(tx,tenant,p['mapping_id'],p['version'])
        if existing:
            if existing['content_hash']!=digest:raise DomainError(409,'immutable_mapping','已登记的映射版本不可覆盖，请创建新版本')
            return existing
        tx.execute('INSERT INTO intake_mappings(tenant_id,mapping_id,version,source_id,schema_version,record_kind,definition,content_hash,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,p['mapping_id'],p['version'],p['source_id'],p['schema_version'],p['record_kind'],_json(p),digest,_now(),str(actor['id'])))
        return self._mapping(tx,tenant,p['mapping_id'],p['version'])

    def _classify(self,tx,tenant,envelope,mapping_id,mapping_version):
        for field,allowed in [('source_category',CATEGORIES),('record_kind',KINDS)]:
            if envelope[field] not in allowed:raise DomainError(422,'needs_mapping','信息类别尚未支持，原文已保留',{'field':field,'value':envelope[field]})
        if envelope['content_type'].lower()!='application/json':
            raise DomainError(422,'needs_mapping','本接口仅转换 JSON；文件原件请通过资产接口保存并引用证据')
        if not mapping_id or not mapping_version:raise DomainError(422,'needs_mapping','尚未指定明确的映射及版本')
        mapping=self._mapping(tx,tenant,mapping_id,mapping_version)
        if not mapping:raise DomainError(422,'needs_mapping','当前租户未登记指定的映射版本')
        definition=mapping['definition']
        for field in ('source_id','schema_version','record_kind','source_category','content_type'):
            if envelope[field]!=definition[field]:raise DomainError(422,'mapping_source_mismatch','来源契约与映射声明不匹配',{'field':field})
        if envelope['source_category']=='model':
            if envelope['record_kind']!='assertion':raise DomainError(422,'model_requires_assertion','外部模型结果只能作为候选断言接收')
            if not envelope.get('producer'):raise DomainError(422,'model_producer_required','外部模型结果必须声明模型名称和版本')
            if not envelope.get('evidence_ids') and not envelope['payload'].get('evidence_ids'):
                raise DomainError(422,'model_evidence_required','外部模型结果必须引用输入原件证据')
        return mapping

    def _normalize(self,definition,envelope):
        body=deepcopy(definition.get('defaults',{}))
        if definition['mode']=='identity':body.update(deepcopy(envelope['payload']))
        else:
            for rule in definition['field_rules']:
                value=_read(envelope['payload'],rule['source_path'])
                if rule.get('source_unit_path') and _read(envelope['payload'],rule['source_unit_path'])!=rule['source_unit']:
                    raise DomainError(422,'source_unit_mismatch','来源单位不符合映射声明',{'source_path':rule['source_unit_path'],'expected':rule['source_unit']})
                if 'enum_map' in rule:
                    if isinstance(value,(dict,list)):raise DomainError(422,'unmapped_enum','枚举来源必须是标量')
                    key=_json(value) if isinstance(value,(bool,type(None))) else str(value)
                    if key not in rule['enum_map']:raise DomainError(422,'unmapped_enum','来源枚举值尚未映射',{'source_path':rule['source_path'],'value':value})
                    value=deepcopy(rule['enum_map'][key])
                kind=rule.get('value_type')
                if kind=='decimal' or 'scale' in rule or 'offset' in rule:
                    with localcontext() as ctx:
                        ctx.prec=70
                        number=_number(value)*_number(rule.get('scale',1))+_number(rule.get('offset',0))
                    if abs(number)>Decimal('1e30') or number.as_tuple().exponent < -24:
                        raise DomainError(422,'invalid_decimal_mapping','转换结果超出支持精度')
                    value=format(number,'f')
                elif kind=='integer':
                    if isinstance(value,bool) or not re.fullmatch(r'-?(0|[1-9][0-9]*)',str(value)):
                        raise DomainError(422,'invalid_integer_mapping','整数转换不接受小数或隐式布尔值')
                    value=int(value)
                elif kind=='datetime':value=_time(value,'mapped datetime')
                elif kind=='boolean' and not isinstance(value,bool):raise DomainError(422,'invalid_boolean_mapping','布尔类型需明确布尔值，其他编码请配置枚举映射')
                elif kind=='string' and not isinstance(value,str):raise DomainError(422,'invalid_string_mapping','字符串类型不能由复杂值隐式转换')
                _write(body,rule['target_path'],value)
                if rule.get('unit'):_write(body,'/value/unit',rule['unit'])
        if definition.get('subject_key'):
            if body.get('subject_key') not in (None,definition['subject_key']):
                raise DomainError(422,'mapping_subject_mismatch','来源对象与映射绑定对象不一致')
            body['subject_key']=definition['subject_key']
        if envelope['record_kind']=='observation':
            if envelope['source_category']=='manual':body['origin']='reported'
            else:body.setdefault('origin','measured')
        if envelope['record_kind']=='assertion':
            body['origin']='model' if envelope['source_category']=='model' else body.get('origin','reported')
        if envelope['record_kind']=='relationship':body['status']='candidate'
        return body

    def _execute(self,tx,tenant,actor,envelope,mapping_id,mapping_version,raw_evidence_id):
        normalized=None;action=None
        try:
            mapping=self._classify(tx,tenant,envelope,mapping_id,mapping_version)
            action=mapping['definition']['target_action']
            self._guard(tenant,actor,self.ACTION_ROLES[action])
            normalized=self._normalize(mapping['definition'],envelope)
            attached=normalized.get('evidence_ids',[])
            if not isinstance(attached,list) or not all(isinstance(x,str) for x in attached):
                raise DomainError(422,'invalid_evidence_ids','证据引用必须为标识字符串数组')
            eids=list(dict.fromkeys(envelope.get('evidence_ids',[])+attached+[raw_evidence_id]))
            if action=='create_event' and normalized.get('event_type') not in {'inspection','irrigation','maintenance','incident'}:
                raise DomainError(422,'external_business_event','本接入模块只保存现场事件；库存业务流程由原平台负责')
            self._evidence(tx,tenant,eids)
            if action not in {'create_entity','create_evidence'}:normalized['evidence_ids']=eids
            schemas=json.loads((Path(__file__).resolve().parents[1]/'contracts'/'input-schemas.json').read_text(encoding='utf-8'))
            schemas.update(CORE_SCHEMAS)
            errors=list(Draft202012Validator(schemas[action],format_checker=FormatChecker()).iter_errors(normalized))
            if errors:raise DomainError(422,'schema_validation_failed','转换后数据不符合目标结构',[{'path':list(e.path),'message':e.message} for e in errors[:20]])
            # A rejected target must not leave partial entities, type assignments or events.
            tx.execute('SAVEPOINT intake_target')
            try:
                result=getattr(self,'_do_'+action)(tx,tenant,actor,normalized)
                target=str(result.get('entity_key') or result.get('id'))
                if action in {'create_entity','create_evidence'}:
                    self._link_evidence(tx,tenant,eids,'entity' if action=='create_entity' else 'evidence',target)
            except Exception:
                tx.execute('ROLLBACK TO SAVEPOINT intake_target');tx.execute('RELEASE SAVEPOINT intake_target')
                raise
            tx.execute('RELEASE SAVEPOINT intake_target')
            return {'status':'stored','issues':[],'normalized_payload':normalized,'target_action':action,'target_id':target,'result':result}
        except DomainError as exc:
            return {'status':'needs_mapping' if exc.code=='needs_mapping' else 'validation_failed','issues':[{'code':exc.code,'message':exc.message,'details':exc.details}],'normalized_payload':normalized,'target_action':action,'target_id':None,'result':None}
        except Exception as exc:
            if type(exc).__name__ in {'IntegrityError','UniqueViolation','ForeignKeyViolation','CheckViolation','NotNullViolation'}:
                return {'status':'validation_failed','issues':[{'code':'integrity_conflict','message':'目标写入违反唯一性或引用约束'}],'normalized_payload':normalized,'target_action':action,'target_id':None,'result':None}
            raise

    def _raw_evidence(self,tx,tenant,actor,envelope):
        raw={'envelope':deepcopy(envelope),'tenant_id':tenant,'actor_id':str(actor['id']),'recorded_at':_now()}
        canonical=_json(raw);digest=_hash(raw)
        return self._do_create_evidence(tx,tenant,actor,{'kind':'structured','uri':'urn:intake:sha256:'+digest,'content_hash':digest,'source_id':envelope['source_id'],'metadata':{'receipt_format':'intake-receipt/1','receipt':raw,'canonical_json':canonical,'producer':envelope.get('producer')}})

    def _receipt(self,tx,tenant,key):
        result=_row(tx.execute('SELECT * FROM intake_receipts WHERE tenant_id=%s AND id=%s',(tenant,_uuid(key,'receipt_id'))).fetchone())
        if not result:raise DomainError(404,'receipt_not_found','接入回执不存在于当前租户')
        result['attempts']=[_row(x) for x in tx.execute('SELECT * FROM intake_attempts WHERE tenant_id=%s AND receipt_id=%s ORDER BY attempt_number',(tenant,result['id'])).fetchall()]
        latest=result['attempts'][-1] if result['attempts'] else {}
        result['issues']=latest.get('issues',[]);result['record']=latest.get('result')
        result['normalized_payload']=latest.get('normalized_payload')
        return result

    def _attempt(self,tx,tenant,actor,receipt,mapping_id,mapping_version):
        attempt=self._execute(tx,tenant,actor,receipt['raw_envelope'],mapping_id,mapping_version,receipt['raw_evidence_id'])
        number=int(receipt['latest_attempt'])+1;now=_now()
        tx.execute('INSERT INTO intake_attempts(tenant_id,receipt_id,attempt_number,mapping_id,mapping_version,status,issues,normalized_payload,target_action,target_id,result,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,receipt['id'],number,mapping_id,mapping_version,attempt['status'],_json(attempt['issues']),_json(attempt['normalized_payload']) if attempt['normalized_payload'] is not None else None,attempt['target_action'],attempt['target_id'],_json(attempt['result']) if attempt['result'] is not None else None,now,str(actor['id'])))
        tx.execute('UPDATE intake_receipts SET status=%s,mapping_id=%s,mapping_version=%s,latest_attempt=%s,target_action=%s,target_id=%s,updated_at=%s WHERE tenant_id=%s AND id=%s',(attempt['status'],mapping_id,mapping_version,number,attempt['target_action'],attempt['target_id'],now,tenant,receipt['id']))
        return self._receipt(tx,tenant,receipt['id'])

    def _do_receive_intake(self,tx,tenant,actor,p):
        _validate('receive_intake',p)
        immutable={k:v for k,v in p.items() if k not in {'mapping_id','mapping_version'}}
        digest=_hash(immutable)
        existing=tx.execute('SELECT id,payload_hash FROM intake_receipts WHERE tenant_id=%s AND source_id=%s AND source_record_id=%s',(tenant,p['source_id'],p['source_record_id'])).fetchone()
        if existing:
            if existing['payload_hash']!=digest:raise DomainError(409,'source_record_conflict','同一来源记录标识的原始内容已存在且不同，不能覆盖')
            return self._receipt(tx,tenant,existing['id'])
        # Reject foreign evidence references before persisting an unauthorized envelope.
        self._evidence(tx,tenant,p.get('evidence_ids',[]),require=False)
        evidence=self._raw_evidence(tx,tenant,actor,p);key=_id();now=_now()
        tx.execute('INSERT INTO intake_receipts(tenant_id,id,source_id,source_record_id,schema_version,source_category,content_type,record_kind,raw_envelope,payload_hash,raw_evidence_id,status,latest_attempt,created_at,created_by,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,key,p['source_id'],p['source_record_id'],p['schema_version'],p['source_category'],p['content_type'],p['record_kind'],_json(p),digest,evidence['id'],'needs_mapping',0,now,str(actor['id']),now))
        self._link_evidence(tx,tenant,[evidence['id']],'intake_receipt',key)
        return self._attempt(tx,tenant,actor,self._receipt(tx,tenant,key),p.get('mapping_id'),p.get('mapping_version'))

    def _do_retry_intake(self,tx,tenant,actor,p):
        _validate('retry_intake',p)
        receipt=self._receipt(tx,tenant,p['receipt_id'])
        if receipt['status']=='stored':raise DomainError(409,'receipt_already_stored','已成功入库的回执不能再次生成业务数据；修订应使用新的来源记录')
        if receipt['latest_attempt']>=100:raise DomainError(422,'retry_limit','单条回执已达到 100 次处理记录，请核对来源后创建修订记录')
        return self._attempt(tx,tenant,actor,receipt,p['mapping_id'],p['mapping_version'])

    def preview_intake(self,tenant,actor,p):
        self._guard(tenant,actor,self.READ_ROLES);_validate('preview_intake',p)
        with self.db.transaction() as tx:
            tx.execute('SAVEPOINT intake_preview')
            try:
                self._evidence(tx,tenant,p.get('evidence_ids',[]),require=False)
                evidence=self._raw_evidence(tx,tenant,actor,p)
                result=self._execute(tx,tenant,actor,p,p.get('mapping_id'),p.get('mapping_version'),evidence['id'])
                result['would_store']=result['status']=='stored';result['read_only']=True
                # Preview-generated UUIDs must not be mistaken for persistent identities.
                result['result']=None;result['target_id']=None
                if result.get('normalized_payload') and 'evidence_ids' in result['normalized_payload']:
                    result['normalized_payload']['evidence_ids']=[x for x in result['normalized_payload'].get('evidence_ids',[]) if x!=evidence['id']]
                return result
            finally:
                tx.execute('ROLLBACK TO SAVEPOINT intake_preview');tx.execute('RELEASE SAVEPOINT intake_preview')

    def query(self,action,tenant,actor,params=None):
        if action=='preview_intake':return self.preview_intake(tenant,actor,params or {})
        if action not in {'mappings','intake_receipts'}:return super().query(action,tenant,actor,params)
        self._guard(tenant,actor,self.READ_ROLES);p=params or {}
        if not isinstance(p,dict):raise DomainError(422,'invalid_query','查询参数必须是对象')
        allowed={'limit','offset','source_id','mapping_id','version'} if action=='mappings' else {'limit','offset','source_id','status','receipt_id'}
        if set(p)-allowed:raise DomainError(422,'unsupported_query','查询参数不受支持',sorted(set(p)-allowed))
        with self.db.transaction() as tx:
            if action=='intake_receipts' and p.get('receipt_id'):return self._receipt(tx,tenant,p['receipt_id'])
            table='intake_mappings' if action=='mappings' else 'intake_receipts';sql='SELECT * FROM '+table+' WHERE tenant_id=%s';args=[tenant]
            for field in allowed-{'limit','offset','receipt_id'}:
                if p.get(field):sql+=' AND '+field+'=%s';args.append(p[field])
            sql+=' ORDER BY created_at,'+('mapping_id,version' if action=='mappings' else 'id')
            page=self._list(tx,sql,args,p)
            page['items']=[_row(x) if action=='mappings' else self._receipt(tx,tenant,x['id']) for x in page['items']]
            return page
