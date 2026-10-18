"""Tenant-scoped ontology, evidence and traceability application service.

The first implementation serializes writes per tenant. This deliberately favors
correctness and reproducible event ordering over unmeasured throughput claims.
PG is authoritative in deployment; the separately named SQLite backend is local
engineering validation only. Business inventory here is an isolated prototype,
not a second production inventory ledger connected to the existing platform.
"""
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import secrets
from uuid import UUID, uuid4


class DomainError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def _now():
    return datetime.now(timezone.utc).isoformat()


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _json(value):
    return json.dumps(_clean(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _id():
    return str(uuid4())


def _uuid(value, field='id'):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise DomainError(422, 'invalid_reference', field + ' must be a UUID')


def _text(data, key, default=None, maximum=500):
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DomainError(422, 'invalid_field', key + ' must be a non-empty bounded string')
    return value.strip()


def _time(value, field='time', optional=False):
    if value is None and optional:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        raise DomainError(422, 'invalid_time', field + ' requires an ISO timestamp with timezone')


def _decimal(value, field='quantity', zero=False):
    if isinstance(value, (float, bool)) or value is None:
        raise DomainError(422, 'invalid_quantity', field + ' must be a decimal string or integer')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise DomainError(422, 'invalid_quantity', field + ' is not decimal')
    if not number.is_finite() or number < 0 or (not zero and number == 0) or number >= Decimal('1e21') or number.as_tuple().exponent < -9:
        raise DomainError(422, 'invalid_quantity', field + ' exceeds supported non-negative decimal precision')
    return number


_JSON_COLUMNS = {'definition','attributes','metadata','value_json','spatial_context','evidence_ids','qualifiers','event_payload','body','payload','response','details','filter_json','members'}


def _unpack(row):
    if row is None:
        return None
    row = dict(row)
    for key in _JSON_COLUMNS:
        if key in row and isinstance(row[key], str):
            row[key] = json.loads(row[key])
    return _clean(row)


class Service:
    CORE_TYPES = {'farm','field','pond','facility','channel','production_system','production_batch','material_lot','package','logistic_unit','device','measurement_point','sample','organization','person','asset'}
    READ_ROLES = {'admin','ontology_admin','operator','reviewer','reader','viewer'}
    REVIEW_ROLES = {'admin','reviewer'}
    ACTION_ROLES = {
        'register_package': {'admin','ontology_admin'},
        'create_entity': {'admin','ontology_admin','operator'},
        'assign_type': {'admin','ontology_admin','operator'},
        'create_evidence': {'admin','operator','reviewer'},
        'withdraw_evidence': REVIEW_ROLES,
        'create_observation': {'admin','operator'},
        'create_assertion': {'admin','operator','reviewer'},
        'review_assertion': REVIEW_ROLES,
        'create_relation': {'admin','ontology_admin','operator','reviewer'},
        'review_relation': REVIEW_ROLES,
        'create_lot': {'admin','operator'},
        'create_event': {'admin','operator'},
        'publish': REVIEW_ROLES,
        'recall': REVIEW_ROLES,
        'create_object_set': {'admin','ontology_admin','operator','reviewer'},
    }

    def __init__(self, db):
        self.db = db

    def _guard(self, tenant, actor, roles):
        if not isinstance(tenant, str) or not tenant.strip() or len(tenant)>100:
            raise DomainError(401, 'tenant_required', 'A tenant identity is required')
        if not isinstance(actor, dict) or not actor.get('id'):
            raise DomainError(401, 'actor_required', 'An authenticated actor is required')
        if actor.get('tenant_id') not in (None, tenant):
            raise DomainError(403, 'tenant_mismatch', 'Actor tenant does not match the requested tenant')
        if not set(actor.get('roles', [])) & roles:
            raise DomainError(403, 'forbidden', 'Actor lacks the required role')
        return str(actor['id'])

    def mutate(self, action, tenant, actor, payload, idempotency_key):
        if action not in self.ACTION_ROLES:
            raise DomainError(404, 'unknown_action', 'Unsupported action')
        actor_id = self._guard(tenant, actor, self.ACTION_ROLES[action])
        if not isinstance(payload, dict):
            raise DomainError(422, 'invalid_payload', 'Payload must be an object')
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
            raise DomainError(422, 'idempotency_required', 'Idempotency-Key is required')
        try:
            digest = _hash({'action':action,'actor':actor_id,'payload':payload})
        except (TypeError, ValueError):
            raise DomainError(422, 'invalid_json', 'Payload must contain finite JSON values')
        try:
            with self.db.transaction() as tx:
                tx.execute('INSERT INTO idempotency(tenant_id,idempotency_key,payload_hash,response,created_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,idempotency_key) DO NOTHING', (tenant,idempotency_key,digest,None,_now()))
                previous = _unpack(tx.execute('SELECT * FROM idempotency WHERE tenant_id=%s AND idempotency_key=%s FOR UPDATE',(tenant,idempotency_key)).fetchone())
                if previous['payload_hash'] != digest:
                    raise DomainError(409,'idempotency_conflict','Idempotency key was used with a different request')
                if previous['response'] is not None:
                    return previous['response']
                # A tenant counter is a transaction lock and a committed-order cursor.
                tx.execute('INSERT INTO outbox_counters(tenant_id,next_sequence) VALUES (%s,%s) ON CONFLICT(tenant_id) DO NOTHING',(tenant,1))
                counter = tx.execute('SELECT next_sequence FROM outbox_counters WHERE tenant_id=%s FOR UPDATE',(tenant,)).fetchone()
                sequence = int(counter['next_sequence'])
                result = getattr(self, '_do_' + action)(tx,tenant,actor,payload)
                result = _clean(result)
                target = str(result.get('entity_key') or result.get('id') or result.get('package_id') or action)
                event_payload = {'target_id':target, 'action':action}
                if result.get('invalidated_publications'):
                    event_payload.update(invalidated_publications=result['invalidated_publications'], invalidation_reason='assertion_conflict')
                # Downstream consumers can resolve a committed source batch or
                # profile without putting its private raw records in the outbox.
                if action in {'import_source_batch','register_source_profile','install_source_bundle'}:
                    source_result = result.get('batch') or result.get('profile') or result
                    for field in ('source_id','batch_id','profile_id','version'):
                        if field in source_result:
                            event_payload[field] = source_result[field]
                    if source_result.get('id'):
                        event_payload['source_ref'] = source_result['id']
                tx.execute('INSERT INTO outbox(tenant_id,sequence,event_id,event_type,aggregate_key,revision,payload,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,sequence,_id(),action,target,int(result.get('revision',1)),_json(event_payload),_now()))
                tx.execute('UPDATE outbox_counters SET next_sequence=%s WHERE tenant_id=%s',(sequence+1,tenant))
                tx.execute('INSERT INTO audit_log(tenant_id,id,actor_id,action,target_id,details,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),actor_id,action,target,_json({'request_hash':digest}),_now()))
                tx.execute('UPDATE idempotency SET response=%s WHERE tenant_id=%s AND idempotency_key=%s',(_json(result),tenant,idempotency_key))
                return result
        except DomainError:
            raise
        except Exception as exc:
            if type(exc).__name__ in {'IntegrityError','UniqueViolation','ForeignKeyViolation','CheckViolation','NotNullViolation'}:
                raise DomainError(409,'integrity_conflict','Write violates a uniqueness, reference or integrity constraint') from exc
            raise

    def _entity(self, tx, tenant, key):
        key = _uuid(key,'entity_key')
        row = _unpack(tx.execute('SELECT * FROM entities WHERE tenant_id=%s AND entity_key=%s',(tenant,key)).fetchone())
        if row is None:
            raise DomainError(404,'entity_not_found','Entity not found in authorized tenant')
        row['semantic_types'] = [_unpack(r) for r in tx.execute('SELECT package_id,package_version,type_id,valid_from,valid_to FROM type_assignments WHERE tenant_id=%s AND entity_key=%s',(tenant,key)).fetchall()]
        return row

    def _lot(self, tx, tenant, key):
        entity = self._entity(tx,tenant,key)
        row = _unpack(tx.execute('SELECT * FROM lots WHERE tenant_id=%s AND lot_key=%s FOR UPDATE',(tenant,entity['entity_key'])).fetchone())
        if row is None:
            raise DomainError(404,'lot_not_found','Material lot not found in authorized tenant')
        row['name'], row['entity_key'], row['id'] = entity['name'], row['lot_key'], row['lot_key']
        row['attributes'] = entity['attributes']
        return row

    def _evidence(self, tx, tenant, ids, require=True, active=True):
        if not isinstance(ids,list) or len(ids)>100 or (require and not ids):
            raise DomainError(422,'evidence_required','Provide one to one hundred evidence IDs')
        result=[]
        for value in dict.fromkeys(ids):
            row=_unpack(tx.execute('SELECT * FROM evidence WHERE tenant_id=%s AND id=%s',(tenant,_uuid(value,'evidence_id'))).fetchone())
            if row is None:
                raise DomainError(404,'evidence_not_found','Evidence not found in authorized tenant')
            if active and row['status']!='active':
                raise DomainError(409,'evidence_withdrawn','Withdrawn evidence cannot support a new adopted record')
            result.append(row)
        return result

    def _link_evidence(self, tx, tenant, ids, kind, target):
        for evidence_id in dict.fromkeys(ids):
            tx.execute('INSERT INTO evidence_links(tenant_id,id,evidence_id,target_kind,target_id,created_at) VALUES (%s,%s,%s,%s,%s,%s)',(tenant,_id(),evidence_id,kind,target,_now()))

    def _do_register_package(self, tx, tenant, actor, p):
        package_id,version,namespace = _text(p,'package_id'),_text(p,'version'),_text(p,'namespace')
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?',version):
            raise DomainError(422,'invalid_version','Package version must be semantic version x.y.z')
        for dep in p.get('dependencies',[]):
            if dep.get('package_id')==package_id:
                raise DomainError(422,'circular_dependency','A package cannot depend on itself')
            if not tx.execute('SELECT 1 FROM ontology_packages WHERE tenant_id=%s AND package_id=%s AND version=%s',(tenant,dep.get('package_id'),dep.get('version'))).fetchone():
                raise DomainError(422,'missing_dependency','Package dependency must be installed at its exact version')
        prior=tx.execute('SELECT package_id FROM ontology_namespaces WHERE tenant_id=%s AND namespace=%s',(tenant,namespace)).fetchone()
        if prior and prior['package_id']!=package_id:
            raise DomainError(409,'namespace_conflict','Namespace belongs to another package')
        if not prior:
            tx.execute('INSERT INTO ontology_namespaces(tenant_id,namespace,package_id) VALUES (%s,%s,%s)',(tenant,namespace,package_id))
        types=p.get('types',[])
        predicates=p.get('predicates',[])
        if not isinstance(types,list) or not types or not isinstance(predicates,list):
            raise DomainError(422,'invalid_package','Package requires type definitions and a predicate list')
        for definition in types:
            _text(definition,'type_id'); _text(definition,'identity_type'); _text(definition,'label')
        for definition in predicates:
            _text(definition,'predicate_id')
            for key in ('subject_types','object_types'):
                if not isinstance(definition.get(key),list) or not definition[key] or not all(isinstance(x,str) and x for x in definition[key]):
                    raise DomainError(422,'invalid_predicate',key+' requires identity type names')
        digest=_hash(p)
        existing=_unpack(tx.execute('SELECT * FROM ontology_packages WHERE tenant_id=%s AND package_id=%s AND version=%s',(tenant,package_id,version)).fetchone())
        if existing:
            if existing['content_hash']!=digest:
                raise DomainError(409,'immutable_release','Published package versions are immutable')
            return existing
        tx.execute('INSERT INTO ontology_packages(tenant_id,package_id,version,namespace,content_hash,definition,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,package_id,version,namespace,digest,_json(p),_now(),str(actor['id'])))
        for d in types:
            tx.execute('INSERT INTO ontology_types(tenant_id,package_id,package_version,type_id,identity_type,definition) VALUES (%s,%s,%s,%s,%s,%s)',(tenant,package_id,version,d['type_id'],d['identity_type'],_json(d)))
        for d in predicates:
            tx.execute('INSERT INTO ontology_predicates(tenant_id,package_id,package_version,predicate_id,definition) VALUES (%s,%s,%s,%s,%s)',(tenant,package_id,version,d['predicate_id'],_json(d)))
        return {'package_id':package_id,'version':version,'namespace':namespace,'content_hash':digest,'status':'published'}

    def _do_create_entity(self, tx, tenant, actor, p):
        entity_type,name = _text(p,'entity_type'),_text(p,'name')
        if entity_type not in self.CORE_TYPES and not tx.execute('SELECT 1 FROM ontology_types WHERE tenant_id=%s AND identity_type=%s',(tenant,entity_type)).fetchone():
            raise DomainError(422,'unknown_identity_type','Register an extension type before creating this identity type')
        attributes=p.get('attrs',{})
        if not isinstance(attributes,dict):
            raise DomainError(422,'invalid_attributes','attrs must be an object')
        key=_uuid(p['entity_key'],'entity_key') if p.get('entity_key') else _id()
        entity_id=_uuid(p['entity_id'],'entity_id') if p.get('entity_id') else _id()
        tx.execute('INSERT INTO entities(tenant_id,entity_key,entity_type,entity_id,name,attributes,revision,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,key,entity_type,entity_id,name,_json(attributes),1,_now(),str(actor['id'])))
        for assignment in p.get('semantic_types',[]):
            self._do_assign_type(tx,tenant,actor,dict(assignment,entity_key=key))
        return self._entity(tx,tenant,key)

    def _do_assign_type(self, tx, tenant, actor, p):
        entity=self._entity(tx,tenant,p.get('entity_key'))
        package_id,version,type_id=_text(p,'package_id'),_text(p,'version'),_text(p,'type_id')
        definition=_unpack(tx.execute('SELECT * FROM ontology_types WHERE tenant_id=%s AND package_id=%s AND package_version=%s AND type_id=%s',(tenant,package_id,version,type_id)).fetchone())
        if definition is None:
            raise DomainError(422,'unknown_semantic_type','Semantic type and release are not registered')
        if definition['identity_type'] not in (entity['entity_type'],'*'):
            raise DomainError(422,'type_identity_mismatch','Semantic classification is incompatible with stable identity type')
        start=_time(p.get('valid_from',_now()),'valid_from'); end=_time(p.get('valid_to'),'valid_to',True)
        if end and end<=start:
            raise DomainError(422,'invalid_interval','valid_to must follow valid_from')
        assignment_id=_id()
        tx.execute('INSERT INTO type_assignments(tenant_id,id,entity_key,package_id,package_version,type_id,valid_from,valid_to,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,assignment_id,entity['entity_key'],package_id,version,type_id,start,end,_now()))
        tx.execute('UPDATE entities SET revision=revision+1 WHERE tenant_id=%s AND entity_key=%s',(tenant,entity['entity_key']))
        return {'id':assignment_id,'entity_key':entity['entity_key'],'type_id':type_id,'package_id':package_id,'version':version,'revision':int(entity['revision'])+1}

    def _do_create_evidence(self, tx, tenant, actor, p):
        kind,uri,content_hash = _text(p,'kind'),_text(p,'uri',maximum=2000),_text(p,'content_hash')
        if not re.fullmatch('[0-9a-fA-F]{64}',content_hash):
            raise DomainError(422,'invalid_hash','content_hash must be SHA-256 hex')
        if not isinstance(p.get('metadata',{}),dict):
            raise DomainError(422,'invalid_metadata','metadata must be an object')
        eid=_id()
        tx.execute('INSERT INTO evidence(tenant_id,id,kind,uri,content_hash,source_id,public_summary,metadata,status,revision,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,eid,kind,uri,content_hash.lower(),str(p.get('source_id','manual')),str(p.get('public_summary',''))[:1000],_json(p.get('metadata',{})),'active',1,_now(),str(actor['id'])))
        return _unpack(tx.execute('SELECT * FROM evidence WHERE tenant_id=%s AND id=%s',(tenant,eid)).fetchone())

    def _do_create_observation(self, tx, tenant, actor, p):
        entity=self._entity(tx,tenant,p.get('subject_key'))
        records=self._evidence(tx,tenant,p.get('evidence_ids',[]))
        value=p.get('value')
        if not isinstance(value,dict) or 'value' not in value or value['value'] is None:
            raise DomainError(422,'invalid_observation','value must be a typed value object; unknown is not zero')
        origin=p.get('origin','measured')
        if origin not in {'measured','reported','estimated'}:
            raise DomainError(422,'invalid_origin','Observation origin must distinguish measured, reported or estimated')
        oid=_id(); evidence_ids=[r['id'] for r in records]
        tx.execute('INSERT INTO observations(tenant_id,id,subject_key,property_id,value_json,observed_at,method,origin,spatial_context,evidence_ids,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,oid,entity['entity_key'],_text(p,'property_id'),_json(value),_time(p.get('observed_at'),'observed_at'),_text(p,'method'),origin,_json(p.get('spatial_context',{})),_json(evidence_ids),_now(),str(actor['id'])))
        self._link_evidence(tx,tenant,evidence_ids,'observation',oid)
        return _unpack(tx.execute('SELECT * FROM observations WHERE tenant_id=%s AND id=%s',(tenant,oid)).fetchone())

    def _do_create_assertion(self, tx, tenant, actor, p):
        if set(p) & {'valid_from','valid_to','known_at','recorded_at','context','scope'}:
            raise DomainError(422,'assertion_context_contract','This prototype stores explicit comparison context inside value.context or value.scope; top-level temporal or scope fields are unsupported and were not ignored')
        if p.get('origin','reported') not in {'reported','derived','forecast','model','manual'}:
            raise DomainError(422,'invalid_origin','Unsupported assertion origin')
        entity=self._entity(tx,tenant,p.get('subject_key'))
        ev=self._evidence(tx,tenant,p.get('evidence_ids',[]))
        has_value='value' in p and p['value'] is not None
        has_object=p.get('object_key') is not None
        if has_value==has_object:
            raise DomainError(422,'assertion_value_exclusive','Provide exactly one of value or object_key')
        object_key=self._entity(tx,tenant,p['object_key'])['entity_key'] if has_object else None
        aid=_id();eids=[x['id'] for x in ev]
        tx.execute('INSERT INTO assertions(tenant_id,id,subject_key,predicate_id,value_json,object_key,origin,evidence_ids,status,revision,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,aid,entity['entity_key'],_text(p,'predicate_id'),_json(p['value']) if has_value else None,object_key,str(p.get('origin','reported')),_json(eids),'candidate',1,_now(),str(actor['id'])))
        self._link_evidence(tx,tenant,eids,'assertion',aid)
        return _unpack(tx.execute('SELECT * FROM assertions WHERE tenant_id=%s AND id=%s',(tenant,aid)).fetchone())

    def _do_review_assertion(self, tx, tenant, actor, p):
        aid=_uuid(p.get('assertion_id'),'assertion_id')
        row=_unpack(tx.execute('SELECT * FROM assertions WHERE tenant_id=%s AND id=%s',(tenant,aid)).fetchone())
        if not row:
            raise DomainError(404,'assertion_not_found','Assertion not found')
        status=p.get('status')
        if status not in {'accepted','rejected'}:
            raise DomainError(422,'invalid_status','Review status must be accepted or rejected')
        if status=='accepted':
            self._evidence(tx,tenant,row['evidence_ids'])
        rationale=_text(p,'rationale',maximum=2000)
        tx.execute('INSERT INTO assertion_assessments(tenant_id,id,assertion_id,status,rationale,actor_id,assessed_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),aid,status,rationale,str(actor['id']),_now()))
        tx.execute('UPDATE assertions SET status=%s,revision=revision+1 WHERE tenant_id=%s AND id=%s',(status,tenant,aid))
        invalidated=[]
        if status=='accepted':
            conflicts=self._assertion_conflicts(tx,tenant,{row['subject_key']})
            conflict_ids={member for conflict in conflicts for member in conflict['member_ids']}
            publication_ids=set()
            for member in sorted(conflict_ids):
                matches=tx.execute('SELECT p.id FROM publications p JOIN publication_assertions a ON a.tenant_id=p.tenant_id AND a.publication_id=p.id WHERE a.tenant_id=%s AND a.assertion_id=%s AND p.status=%s',(tenant,member,'published')).fetchall()
                publication_ids.update(str(item['id']) for item in matches)
            for publication_id in sorted(publication_ids):
                self._invalidate_publication(tx,tenant,publication_id,'withdrawn')
                tx.execute('INSERT INTO audit_log(tenant_id,id,actor_id,action,target_id,details,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),str(actor['id']),'publication.invalidated',publication_id,_json({'reason':'assertion_conflict','trigger_assertion_id':aid,'conflict_member_ids':sorted(conflict_ids)}),_now()))
                invalidated.append(publication_id)
        if status!='accepted':
            for pub in tx.execute('SELECT publication_id FROM publication_assertions WHERE tenant_id=%s AND assertion_id=%s',(tenant,aid)).fetchall():
                self._invalidate_publication(tx,tenant,str(pub['publication_id']),'withdrawn')
        result=_unpack(tx.execute('SELECT * FROM assertions WHERE tenant_id=%s AND id=%s',(tenant,aid)).fetchone())
        if invalidated:
            result['invalidated_publications']=invalidated
        return result

    def _do_create_relation(self, tx, tenant, actor, p):
        subject=self._entity(tx,tenant,p.get('subject_key')); obj=self._entity(tx,tenant,p.get('object_key'))
        package,version,predicate=_text(p,'package_id'),_text(p,'package_version'),_text(p,'predicate_id')
        definition=_unpack(tx.execute('SELECT * FROM ontology_predicates WHERE tenant_id=%s AND package_id=%s AND package_version=%s AND predicate_id=%s',(tenant,package,version,predicate)).fetchone())
        if not definition:
            raise DomainError(422,'unknown_predicate','Register the predicate and its release first')
        d=definition['definition']
        for entity,key in ((subject,'subject_types'),(obj,'object_types')):
            if entity['entity_type'] not in d[key] and '*' not in d[key]:
                raise DomainError(422,'relation_endpoint_type','Relation endpoint violates the registered predicate')
        start=_time(p.get('valid_from'),'valid_from');end=_time(p.get('valid_to'),'valid_to',True)
        if end and end<=start:
            raise DomainError(422,'invalid_interval','Relation valid_to must follow valid_from')
        eids=[x['id'] for x in self._evidence(tx,tenant,p.get('evidence_ids',[]))]
        status=p.get('status','candidate')
        if status not in {'candidate','accepted'}:
            raise DomainError(422,'invalid_status','New relation status must be candidate or accepted')
        if status=='accepted':
            self._guard(tenant,actor,self.REVIEW_ROLES)
        if d.get('irreflexive') and subject['entity_key']==obj['entity_key']:
            raise DomainError(422,'relation_self_loop','Predicate is irreflexive')
        if d.get('acyclic'):
            # Cycle check respects this exact predicate release. No causality inference.
            edges=tx.execute('SELECT subject_key,object_key FROM relations WHERE tenant_id=%s AND package_id=%s AND package_version=%s AND predicate_id=%s AND status=%s',(tenant,package,version,predicate,'accepted')).fetchall()
            graph={}
            for edge in edges:
                graph.setdefault(str(edge['subject_key']),[]).append(str(edge['object_key']))
            pending=[obj['entity_key']];seen=set()
            while pending:
                item=pending.pop()
                if item==subject['entity_key']:
                    raise DomainError(422,'relation_cycle','Predicate requires an acyclic relation network')
                if item not in seen:
                    seen.add(item);pending.extend(graph.get(item,[]))
        rid=_id()
        tx.execute('INSERT INTO relations(tenant_id,id,subject_key,object_key,package_id,package_version,predicate_id,dimension,valid_from,valid_to,qualifiers,evidence_ids,status,revision,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,rid,subject['entity_key'],obj['entity_key'],package,version,predicate,str(d.get('dimension','domain')),start,end,_json(p.get('qualifiers',{})),_json(eids),status,1,_now(),str(actor['id'])))
        self._link_evidence(tx,tenant,eids,'relation',rid)
        assessment_id=None
        if status=='accepted':
            assessment_id=_id()
            tx.execute('INSERT INTO relation_assessments(tenant_id,id,relation_id,status,rationale,actor_id,assessed_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,assessment_id,rid,status,str(p.get('rationale','Direct creation by authorized reviewer')),str(actor['id']),_now()))
        row=_unpack(tx.execute('SELECT * FROM relations WHERE tenant_id=%s AND id=%s',(tenant,rid)).fetchone())
        row['predicate_release_id']=package+'@'+version;row['assessment_ref']=assessment_id
        return row

    def _do_review_relation(self, tx, tenant, actor, p):
        rid=_uuid(p.get('relation_id'),'relation_id')
        row=_unpack(tx.execute('SELECT * FROM relations WHERE tenant_id=%s AND id=%s',(tenant,rid)).fetchone())
        if not row:
            raise DomainError(404,'relation_not_found','Relation not found')
        status=p.get('status')
        if status not in {'accepted','rejected'}:
            raise DomainError(422,'invalid_status','Review status must be accepted or rejected')
        if status=='accepted':
            self._evidence(tx,tenant,row['evidence_ids'])
            definition=_unpack(tx.execute('SELECT definition FROM ontology_predicates WHERE tenant_id=%s AND package_id=%s AND package_version=%s AND predicate_id=%s',(tenant,row['package_id'],row['package_version'],row['predicate_id'])).fetchone())['definition']
            if definition.get('acyclic'):
                # Reuse full validation before adoption, without creating another relation.
                edges=tx.execute('SELECT subject_key,object_key FROM relations WHERE tenant_id=%s AND package_id=%s AND package_version=%s AND predicate_id=%s AND status=%s AND id<>%s',(tenant,row['package_id'],row['package_version'],row['predicate_id'],'accepted',rid)).fetchall()
                graph={}
                for edge in edges:
                    graph.setdefault(str(edge['subject_key']),[]).append(str(edge['object_key']))
                queue=[row['object_key']];seen=set()
                while queue:
                    key=queue.pop()
                    if key==row['subject_key']:
                        raise DomainError(422,'relation_cycle','Adoption would create a cycle')
                    if key not in seen:
                        seen.add(key);queue.extend(graph.get(key,[]))
        assessment_id=_id()
        tx.execute('INSERT INTO relation_assessments(tenant_id,id,relation_id,status,rationale,actor_id,assessed_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,assessment_id,rid,status,_text(p,'rationale',maximum=2000),str(actor['id']),_now()))
        tx.execute('UPDATE relations SET status=%s,revision=revision+1 WHERE tenant_id=%s AND id=%s',(status,tenant,rid))
        row=_unpack(tx.execute('SELECT * FROM relations WHERE tenant_id=%s AND id=%s',(tenant,rid)).fetchone())
        row['assessment_ref']=assessment_id
        return row

    def _do_create_lot(self, tx, tenant, actor, p):
        if p.get('initial_quantity') is not None and _decimal(p['initial_quantity'],zero=True)!=0:
            raise DomainError(422,'opening_quantity_forbidden','Create a supported harvest or conversion event to establish quantity')
        production_key=None
        if p.get('production_batch_key'):
            batch=self._entity(tx,tenant,p['production_batch_key'])
            if batch['entity_type']!='production_batch':
                raise DomainError(422,'batch_type','production_batch_key must refer to a production batch')
            production_key=batch['entity_key']
        entity=self._do_create_entity(tx,tenant,actor,{'entity_type':'material_lot','name':_text(p,'name'),'attrs':p.get('attrs',{}),'semantic_types':p.get('semantic_types',[])})
        key=entity['entity_key']
        tx.execute('INSERT INTO lots(tenant_id,lot_key,product_type,unit,production_batch_key,produced_quantity,available_quantity,shipped_quantity,received_quantity,revision) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,key,_text(p,'product_type'),_text(p,'unit'),production_key,'0','0','0','0',1))
        return self._lot(tx,tenant,key)

    def _items(self, tx, tenant, items, label):
        if not isinstance(items,list) or len(items)>100:
            raise DomainError(422,'invalid_items',label+' must be a list of at most 100 rows')
        result=[];seen=set()
        for item in sorted(items,key=lambda x:str(x.get('lot_key','')) if isinstance(x,dict) else ''):
            if not isinstance(item,dict):
                raise DomainError(422,'invalid_item','Material participant must be an object')
            lot=self._lot(tx,tenant,item.get('lot_key'))
            if lot['lot_key'] in seen:
                raise DomainError(422,'duplicate_lot','A lot may occur only once per participant role')
            seen.add(lot['lot_key'])
            unit=_text(item,'unit')
            if unit!=lot['unit']:
                raise DomainError(422,'unit_mismatch','Explicitly normalize units before booking material quantities')
            quantity=_decimal(item.get('quantity'))
            if unit in {'count','item','piece'} and quantity!=quantity.to_integral_value():
                raise DomainError(422,'fractional_count','Discrete units require integer quantity')
            result.append({'lot':lot,'lot_key':lot['lot_key'],'quantity':quantity,'unit':unit})
        return result

    def _do_create_event(self, tx, tenant, actor, p):
        kind=_text(p,'event_type')
        if kind not in {'harvest','split','merge','transform','package','ship','receive'}:
            raise DomainError(422,'unsupported_event','This event profile is not implemented; no generic quantity mutation is allowed')
        occurred=_time(p.get('occurred_at'),'occurred_at')
        if p.get('supersedes_id'):
            raise DomainError(422,'correction_requires_reversal','Quantity event corrections require an explicit reversal workflow, not a replacement record; not implemented in this prototype')
        eids=[x['id'] for x in self._evidence(tx,tenant,p.get('evidence_ids',[]))]
        participants=p.get('participants',[])
        if not isinstance(participants,list) or len(participants)>100:
            raise DomainError(422,'invalid_participants','participants must be a bounded list')
        resolved=[]
        for item in participants:
            entity=self._entity(tx,tenant,item.get('entity_key'))
            role=_text(item,'role')
            if role in {'input','output','shipped_item','received_item'}:
                raise DomainError(422,'reserved_role','Material quantity roles must use the typed items/inputs/outputs fields')
            resolved.append((entity,role,item))
        inputs=self._items(tx,tenant,p.get('inputs',[]),'inputs')
        outputs=self._items(tx,tenant,p.get('outputs',[]),'outputs')
        ins={x['lot_key'] for x in inputs};outs={x['lot_key'] for x in outputs}
        if ins & outs:
            raise DomainError(422,'material_cycle','Input and output material lots must be distinct')
        if kind=='harvest':
            origins=[x[0] for x in resolved if x[1]=='production_origin']
            if inputs or not outputs or not origins or any(x['entity_type']!='production_batch' for x in origins):
                raise DomainError(422,'harvest_roles','Harvest requires outputs and production_origin production batch participants, with no material inputs')
            for output in outputs:
                registered=output['lot']['production_batch_key']
                if registered and registered not in {x['entity_key'] for x in origins}:
                    raise DomainError(422,'production_origin_mismatch','Lot production batch does not match harvest origin')
        elif kind in {'split','merge','transform'}:
            if not inputs or not outputs:
                raise DomainError(422,'conversion_roles','Conversion requires material inputs and outputs')
            if kind=='split' and (len(inputs)!=1 or len(outputs)<2):
                raise DomainError(422,'split_roles','Split requires one input and at least two outputs')
            if kind=='merge' and (len(inputs)<2 or len(outputs)!=1):
                raise DomainError(422,'merge_roles','Merge requires at least two inputs and one output')
            units={x['unit'] for x in inputs+outputs}
            if len(units)!=1:
                raise DomainError(422,'incomparable_quantities','Mass balance requires the same explicit unit and measurement basis')
            if kind=='transform' and 'loss_quantity' not in p:
                raise DomainError(422,'loss_required','Transformation requires explicit loss_quantity, including zero')
            loss=_decimal(p.get('loss_quantity','0'),'loss_quantity',True)
            if loss>0 and p.get('loss_unit')!=next(iter(units)):
                raise DomainError(422,'loss_unit','Loss requires the same unit as material inputs')
            if sum((x['quantity'] for x in inputs),Decimal(0)) != sum((x['quantity'] for x in outputs),Decimal(0))+loss:
                raise DomainError(422,'mass_balance','Inputs must equal outputs plus explicit loss in this processing profile')
            if kind in {'split','merge'} and loss!=0:
                raise DomainError(422,'split_merge_loss','Use transformation for material loss; split and merge conserve quantity')
        elif inputs or outputs:
            raise DomainError(422,'non_conversion_inputs','Package and transport events do not create material conversion ancestry')
        if kind=='package':
            containers=[x for x in resolved if x[1]=='container']
            children=[x for x in resolved if x[1]=='contained_item']
            if len(containers)!=1 or not children or containers[0][0]['entity_type'] not in {'package','logistic_unit'}:
                raise DomainError(422,'packaging_roles','Package requires one package/logistic_unit container and contained items')
            if any(x[0]['entity_type'] not in {'material_lot','package','logistic_unit'} for x in children) or any(x[0]['entity_key']==containers[0][0]['entity_key'] for x in children):
                raise DomainError(422,'packaging_child','Invalid container child')
        for item in inputs:
            if self._active_recall(tx,tenant,item['lot_key']):
                raise DomainError(409,'lot_recalled','Recalled or possibly affected material cannot be consumed by this prototype; controlled rework is not implemented')
            if not item['lot']['genesis_event_id'] or Decimal(str(item['lot']['available_quantity']))<item['quantity']:
                raise DomainError(409,'insufficient_stock','Material input exceeds available quantity')
        for item in outputs:
            if item['lot']['genesis_event_id']:
                raise DomainError(409,'lot_already_produced','Output lot already has a genesis event; create a new output lot')
        transit=[]
        if kind in {'ship','receive'}:
            transit=self._items(tx,tenant,p.get('items',[]),'items')
            if not transit:
                raise DomainError(422,'shipment_items','Transport event requires items')
        shipment_id=None
        if kind=='ship':
            for item in transit:
                if self._active_recall(tx,tenant,item['lot_key']):
                    raise DomainError(409,'lot_recalled','Recalled or possibly affected material cannot be shipped')
                if not item['lot']['genesis_event_id'] or Decimal(str(item['lot']['available_quantity']))<item['quantity']:
                    raise DomainError(409,'insufficient_stock','Shipping exceeds available material quantity')
        if kind=='receive':
            shipment_id=_uuid(p.get('shipment_id'),'shipment_id')
            shipment=tx.execute('SELECT event_type,occurred_at FROM events WHERE tenant_id=%s AND id=%s',(tenant,shipment_id)).fetchone()
            if not shipment or shipment['event_type']!='ship':
                raise DomainError(404,'shipment_not_found','Shipment not found in authorized tenant')
            if occurred<_time(shipment['occurred_at']):
                raise DomainError(422,'event_order','Receipt cannot precede shipment')
            for item in transit:
                line=tx.execute('SELECT * FROM shipment_lines WHERE tenant_id=%s AND shipment_id=%s AND lot_key=%s FOR UPDATE',(tenant,shipment_id,item['lot_key'])).fetchone()
                if not line or Decimal(str(line['shipped_quantity']))-Decimal(str(line['received_quantity']))<item['quantity']:
                    raise DomainError(409,'over_receipt','Receipt exceeds unreceived shipment quantity')
                item['line']=dict(line)
        # Temporal genealogy: an output cannot be consumed before its source event.
        for item in inputs+transit:
            genesis=item['lot']['genesis_event_id']
            if genesis:
                created=tx.execute('SELECT occurred_at FROM events WHERE tenant_id=%s AND id=%s',(tenant,genesis)).fetchone()
                if occurred<_time(created['occurred_at']):
                    raise DomainError(422,'event_order','Material use cannot precede production')
        event_id=_id()
        event_payload=dict(p);event_payload['quantity_profile']='same_unit_exact_balance' if kind in {'split','merge','transform'} else 'not_applicable'
        tx.execute('INSERT INTO events(tenant_id,id,event_type,occurred_at,event_payload,evidence_ids,status,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,event_id,kind,occurred,_json(event_payload),_json(eids),'reported',_now(),str(actor['id'])))
        for entity,role,item in resolved:
            tx.execute('INSERT INTO event_participants(tenant_id,id,event_id,entity_key,role,quantity,unit) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),event_id,entity['entity_key'],role,None,None))
        for role,items in (('input',inputs),('output',outputs)):
            for item in items:
                tx.execute('INSERT INTO event_participants(tenant_id,id,event_id,entity_key,role,quantity,unit) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),event_id,item['lot_key'],role,str(item['quantity']),item['unit']))
        for item in inputs:
            remaining=Decimal(str(item['lot']['available_quantity']))-item['quantity']
            tx.execute('UPDATE lots SET available_quantity=%s,revision=revision+1 WHERE tenant_id=%s AND lot_key=%s',(str(remaining),tenant,item['lot_key']))
        for item in outputs:
            tx.execute('UPDATE lots SET produced_quantity=%s,available_quantity=%s,genesis_event_id=%s,revision=revision+1 WHERE tenant_id=%s AND lot_key=%s',(str(item['quantity']),str(item['quantity']),event_id,tenant,item['lot_key']))
        for item in inputs:
            for output in outputs:
                # One input has definite ancestry. Multi-input allocation is unknown.
                allocation='known_source' if len(inputs)==1 else 'possible_contribution'
                amount=str(output['quantity']) if len(inputs)==1 else None
                tx.execute('INSERT INTO material_ancestry(tenant_id,event_id,input_lot_key,output_lot_key,allocation_status,allocation_quantity,unit) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,event_id,item['lot_key'],output['lot_key'],allocation,amount,item['unit']))
        for item in transit:
            role='shipped_item' if kind=='ship' else 'received_item'
            tx.execute('INSERT INTO event_participants(tenant_id,id,event_id,entity_key,role,quantity,unit) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),event_id,item['lot_key'],role,str(item['quantity']),item['unit']))
            if kind=='ship':
                remaining=Decimal(str(item['lot']['available_quantity']))-item['quantity']
                shipped=Decimal(str(item['lot']['shipped_quantity']))+item['quantity']
                tx.execute('UPDATE lots SET available_quantity=%s,shipped_quantity=%s,revision=revision+1 WHERE tenant_id=%s AND lot_key=%s',(str(remaining),str(shipped),tenant,item['lot_key']))
                tx.execute('INSERT INTO shipment_lines(tenant_id,shipment_id,lot_key,shipped_quantity,received_quantity,unit) VALUES (%s,%s,%s,%s,%s,%s)',(tenant,event_id,item['lot_key'],str(item['quantity']),'0',item['unit']))
            else:
                received=Decimal(str(item['line']['received_quantity']))+item['quantity']
                total=Decimal(str(item['lot']['received_quantity']))+item['quantity']
                tx.execute('UPDATE shipment_lines SET received_quantity=%s WHERE tenant_id=%s AND shipment_id=%s AND lot_key=%s',(str(received),tenant,shipment_id,item['lot_key']))
                tx.execute('UPDATE lots SET received_quantity=%s,revision=revision+1 WHERE tenant_id=%s AND lot_key=%s',(str(total),tenant,item['lot_key']))
        self._link_evidence(tx,tenant,eids,'event',event_id)
        return _unpack(tx.execute('SELECT * FROM events WHERE tenant_id=%s AND id=%s',(tenant,event_id)).fetchone())

    def _active_recall(self, tx, tenant, lot_key):
        return bool(tx.execute('SELECT 1 FROM recall_lots l JOIN recalls r ON r.tenant_id=l.tenant_id AND r.id=l.recall_id WHERE l.tenant_id=%s AND l.lot_key=%s AND r.status=%s',(tenant,lot_key,'active')).fetchone())

    def _assertion_conflicts(self, tx, tenant, subject_keys):
        """Conservative comparison of adopted claims; observations are not mixed in.

        Qualifiers remain part of the comparison key. Different units, methods,
        time windows or scopes are not declared contradictory. Free text can
        only flag an unresolved difference, not prove a logical contradiction.
        """
        groups={}
        qualifier_keys={'context','scope','unit','method','time_scope','spatial_scope','measurement_basis','valid_time','forecast_valid_time','issued_at'}
        annotations={'public_text','description','note','confidence','score','uncertainty','model_version'}
        for key in sorted(subject_keys):
            rows=tx.execute('SELECT * FROM assertions WHERE tenant_id=%s AND subject_key=%s AND status=%s',(tenant,key,'accepted')).fetchall()
            for raw in rows:
                row=_unpack(raw);value=row['value_json']
                if isinstance(value,dict):
                    scope={k:value[k] for k in sorted(qualifier_keys) if k in value}
                    substantive={k:v for k,v in value.items() if k not in qualifier_keys | annotations}
                    structured=bool(substantive)
                    if not structured:
                        substantive={'unstructured_text':value.get('public_text',value.get('description',''))}
                    if isinstance(substantive.get('value'),(str,int)) and not isinstance(substantive.get('value'),bool):
                        try:
                            number=Decimal(str(substantive['value']))
                            if number.is_finite():substantive['value']=str(number.normalize())
                        except InvalidOperation:pass
                else:
                    scope={};substantive={'object_key':row['object_key']} if row['object_key'] else {'value':value};structured=True
                comparison=_json({'subject_key':row['subject_key'],'predicate_id':row['predicate_id'],'scope':scope})
                group=groups.setdefault(comparison,{'subject_key':row['subject_key'],'predicate_id':row['predicate_id'],'scope':scope,'rows':[]})
                group['rows'].append((row['id'],_hash(substantive),structured))
        conflicts=[]
        for group in groups.values():
            if len({item[1] for item in group['rows']})>1:
                conflicts.append({'subject_key':group['subject_key'],'predicate_id':group['predicate_id'],'comparison_scope':group['scope'],'member_ids':[item[0] for item in group['rows']],'status':'unresolved','kind':'comparable_value_disagreement' if all(item[2] for item in group['rows']) else 'unstructured_difference','note':'The prototype does not rank sources or automatically decide truth; a missing scope remains an unqualified claim, not a universal statement'})
        return conflicts

    def _lineage(self, tx, tenant, lot_key, direction='upstream', depth=10, maximum=200):
        if direction not in {'upstream','downstream'}:
            raise DomainError(422,'invalid_direction','direction must be upstream or downstream')
        depth=max(1,min(int(depth),30)); maximum=max(1,min(int(maximum),2000))
        root=self._lot(tx,tenant,lot_key);seen={root['lot_key']};frontier=[root['lot_key']];edges=[];edge_ids=set();truncated=False
        from_col,to_col=('output_lot_key','input_lot_key') if direction=='upstream' else ('input_lot_key','output_lot_key')
        for level in range(depth):
            next_frontier=[]
            for key in frontier:
                rows=tx.execute('SELECT * FROM material_ancestry WHERE tenant_id=%s AND '+from_col+'=%s',(tenant,key)).fetchall()
                for raw in rows:
                    edge=_unpack(raw);other=edge[to_col];signature=(edge['event_id'],edge['input_lot_key'],edge['output_lot_key'])
                    if other not in seen and len(seen)>=maximum:
                        truncated=True;continue
                    if signature not in edge_ids:
                        edge_ids.add(signature);edges.append(edge)
                    if other not in seen:
                        seen.add(other);next_frontier.append(other)
            frontier=next_frontier
            if not frontier:
                break
        if frontier:
            for key in frontier:
                if tx.execute('SELECT 1 FROM material_ancestry WHERE tenant_id=%s AND '+from_col+'=%s',(tenant,key)).fetchone():
                    truncated=True
        nodes=[self._lot(tx,tenant,key) for key in sorted(seen)]
        gaps=[]
        if truncated:
            gaps.append({'code':'traversal_truncated','message':'Depth or node budget prevented exhaustive traversal'})
        for node in nodes:
            if not node['genesis_event_id']:
                gaps.append({'code':'missing_genesis','lot_key':node['lot_key']})
        if any(x['allocation_status']=='possible_contribution' for x in edges):
            gaps.append({'code':'allocation_unknown','message':'Multiple-input contribution is not individually quantified'})
        return {'root_key':root['lot_key'],'direction':direction,'nodes':nodes,'edges':edges,'truncated':truncated,'gaps':gaps}

    def _trace_bundle(self, tx, tenant, lot_key):
        graph=self._lineage(tx,tenant,lot_key,'upstream',20,500)
        events={};evidence_ids=set();entity_keys=set()
        relevant_event_ids={edge['event_id'] for edge in graph['edges']} | {node['genesis_event_id'] for node in graph['nodes'] if node['genesis_event_id']}
        for node in graph['nodes']:
            entity_keys.add(node['lot_key'])
            if node['production_batch_key']:
                entity_keys.add(node['production_batch_key'])
            rows=tx.execute('SELECT e.* FROM events e JOIN event_participants p ON p.tenant_id=e.tenant_id AND p.event_id=e.id WHERE p.tenant_id=%s AND p.entity_key=%s',(tenant,node['lot_key'])).fetchall()
            for raw in rows:
                event=_unpack(raw)
                if node['lot_key']!=graph['root_key'] and event['id'] not in relevant_event_ids:
                    continue
                events[event['id']]=event;evidence_ids.update(event['evidence_ids'])
        event_rows=[]
        for event in sorted(events.values(),key=lambda x:(x['occurred_at'],x['id'])):
            participants=[_unpack(x) for x in tx.execute('SELECT * FROM event_participants WHERE tenant_id=%s AND event_id=%s',(tenant,event['id'])).fetchall()]
            event['participants']=participants
            entity_keys.update(x['entity_key'] for x in participants if x['role']=='production_origin')
            event_rows.append(event)
        evidence=self._evidence(tx,tenant,sorted(evidence_ids),require=False,active=False)
        gaps=list(graph['gaps'])
        for record in evidence:
            if record['status']!='active':
                gaps.append({'code':'evidence_withdrawn','evidence_id':record['id']})
        if not event_rows:
            gaps.append({'code':'no_business_events'})
        root=self._lot(tx,tenant,lot_key)
        recalls=[_unpack(x) for x in tx.execute('SELECT r.id,r.reason,r.status,l.scope_status FROM recalls r JOIN recall_lots l ON l.tenant_id=r.tenant_id AND l.recall_id=r.id WHERE l.tenant_id=%s AND l.lot_key=%s AND r.status=%s',(tenant,root['lot_key'],'active')).fetchall()]
        latest=tx.execute('SELECT next_sequence FROM outbox_counters WHERE tenant_id=%s',(tenant,)).fetchone()
        return {'schema_version':'1.0.0','bundle_type':'TraceabilityBundle','subject_ref':root['lot_key'],'lot':root,'material_genealogy':graph,'events':event_rows,'evidence':evidence,'allowed_subject_keys':sorted(entity_keys),'quality_release_status':'not_evaluated','conflicts':self._assertion_conflicts(tx,tenant,entity_keys),'recalls':recalls,'completeness':{'material':'partial' if gaps else 'complete','evidence':'partial' if any(x['status']!='active' for x in evidence) else ('complete' if evidence else 'unknown'),'quality':'unknown','logistics':'partial' if any(x['event_type']=='ship' for x in event_rows) else 'unknown'},'gaps':gaps,'source_snapshot_id':str(int(latest['next_sequence'])-1) if latest else '0','generated_at':_now(),'limitations':['Recorded evidence does not independently establish real-world occurrence or product certification','Current projection only; historical as-of reconstruction is not implemented']}

    def _invalidate_publication(self, tx, tenant, publication_id, status):
        # Body and content hash remain immutable. Only current status envelope changes.
        tx.execute('UPDATE publications SET status=%s WHERE tenant_id=%s AND id=%s',(status,tenant,publication_id))
        tx.execute('UPDATE public_codes SET status=%s,revision=revision+1 WHERE tenant_id=%s AND publication_id=%s',(status,tenant,publication_id))

    def _do_withdraw_evidence(self, tx, tenant, actor, p):
        eid=_uuid(p.get('evidence_id'),'evidence_id');reason=_text(p,'reason',maximum=2000)
        row=self._evidence(tx,tenant,[eid],active=False)[0]
        if row['status']=='withdrawn':
            return row
        tx.execute('UPDATE evidence SET status=%s,revision=revision+1,withdrawn_at=%s,withdrawal_reason=%s WHERE tenant_id=%s AND id=%s',('withdrawn',_now(),reason,tenant,eid))
        for linked in tx.execute('SELECT target_kind,target_id FROM evidence_links WHERE tenant_id=%s AND evidence_id=%s',(tenant,eid)).fetchall():
            if linked['target_kind']=='assertion':
                aid=str(linked['target_id'])
                tx.execute('UPDATE assertions SET status=%s,revision=revision+1 WHERE tenant_id=%s AND id=%s',('needs_review',tenant,aid))
                tx.execute('INSERT INTO assertion_assessments(tenant_id,id,assertion_id,status,rationale,actor_id,assessed_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),aid,'needs_review','Evidence withdrawn: '+reason,str(actor['id']),_now()))
            elif linked['target_kind']=='relation':
                rid=str(linked['target_id'])
                tx.execute('UPDATE relations SET status=%s,revision=revision+1 WHERE tenant_id=%s AND id=%s',('needs_review',tenant,rid))
                tx.execute('INSERT INTO relation_assessments(tenant_id,id,relation_id,status,rationale,actor_id,assessed_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,_id(),rid,'needs_review','Evidence withdrawn: '+reason,str(actor['id']),_now()))
        affected=[]
        for pub in tx.execute('SELECT publication_id FROM publication_evidence WHERE tenant_id=%s AND evidence_id=%s',(tenant,eid)).fetchall():
            publication_id=str(pub['publication_id']);affected.append(publication_id)
            self._invalidate_publication(tx,tenant,publication_id,'withdrawn')
        row=self._evidence(tx,tenant,[eid],active=False)[0];row['affected_publications']=affected
        return row

    def _do_publish(self, tx, tenant, actor, p):
        lot=self._lot(tx,tenant,p.get('lot_key'))
        bundle=self._trace_bundle(tx,tenant,lot['lot_key'])
        if not lot['genesis_event_id']:
            raise DomainError(409,'unproduced_lot','A lot without production evidence cannot be published')
        if bundle['recalls']:
            raise DomainError(409,'lot_recalled','An active recall prevents publication')
        if any(x['status']!='active' for x in bundle['evidence']):
            raise DomainError(409,'evidence_withdrawn','Trace depends on withdrawn evidence; correct the source before publication')
        summary=p.get('summary',{})
        if not isinstance(summary,dict) or set(summary)-{'product_name','origin','description'} or any(not isinstance(x,str) or len(x)>2000 for x in summary.values()):
            raise DomainError(422,'public_whitelist','summary allows only product_name, origin and description strings')
        assertions=[];ev_ids={x['id'] for x in bundle['evidence']}
        asserted=p.get('assertion_ids',[])
        if not isinstance(asserted,list) or len(asserted)>100:
            raise DomainError(422,'invalid_assertions','assertion_ids must be a bounded list')
        conflicted_ids={aid for conflict in bundle['conflicts'] for aid in conflict['member_ids']}
        if set(asserted) & conflicted_ids:
            raise DomainError(409,'unresolved_assertion_conflict','Selected accepted assertions have unresolved comparable disagreements; review and reject or revise the unsupported assertion before publishing')
        for value in dict.fromkeys(asserted):
            aid=_uuid(value,'assertion_id')
            row=_unpack(tx.execute('SELECT * FROM assertions WHERE tenant_id=%s AND id=%s',(tenant,aid)).fetchone())
            if row is None:
                raise DomainError(404,'assertion_not_found','Assertion not found')
            if row['status']!='accepted':
                raise DomainError(409,'assertion_not_accepted','Only accepted assertions may be selected for publication')
            if row['subject_key'] not in bundle['allowed_subject_keys']:
                raise DomainError(422,'assertion_scope','Assertion does not apply to the traced subject or its recorded source')
            ev_ids.update(x['id'] for x in self._evidence(tx,tenant,row['evidence_ids']))
            # Reviewer explicitly publishes a bounded text statement, never raw model fields.
            value_json=row['value_json']
            text=value_json.get('public_text') if isinstance(value_json,dict) else None
            if not isinstance(text,str) or not text.strip() or len(text)>1000:
                raise DomainError(422,'public_statement_required','Published assertions require a reviewed value.public_text')
            assertions.append({'assertion_id':aid,'statement':text,'origin':row['origin'],'review_status':'accepted'})
        for record in self._evidence(tx,tenant,p.get('evidence_ids',[]),require=False):
            if record['id'] not in ev_ids:
                raise DomainError(422,'evidence_scope','Publication evidence must be linked to trace events or selected assertions')
        records=self._evidence(tx,tenant,sorted(ev_ids),require=False)
        previous=tx.execute('SELECT MAX(revision) AS revision FROM publications WHERE tenant_id=%s AND lot_key=%s',(tenant,lot['lot_key'])).fetchone()
        revision=int(previous['revision'] or 0)+1
        publication_id=_id()
        public_body={'schema_version':'1.0.0','bundle_type':'PublicTraceabilityView','product':{'product_name':summary.get('product_name',lot['name']),'origin':summary.get('origin',''),'description':summary.get('description',''),'product_type':lot['product_type']},'timeline':[{'event_type':e['event_type'],'occurred_at':e['occurred_at'],'occurrence_status':e['status']} for e in bundle['events']],'quality_statements':[{key:value for key,value in statement.items() if key!='assertion_id'} for statement in assertions],'quality_release_status':'not_evaluated','evidence_summaries':[{'kind':e['kind'],'summary':e['public_summary'],'content_hash':e['content_hash']} for e in records],'completeness':bundle['completeness'],'gaps':[{'code':x['code']} for x in bundle['gaps']],'source_snapshot_id':bundle['source_snapshot_id'],'published_at':_now(),'notice':'Published trace information is not automatic product certification; recorded events require real-world validation.'}
        digest=_hash(public_body)
        tx.execute('INSERT INTO publications(tenant_id,id,lot_key,revision,body,content_hash,status,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,publication_id,lot['lot_key'],revision,_json(public_body),digest,'published',_now(),str(actor['id'])))
        for eid in sorted(ev_ids):
            tx.execute('INSERT INTO publication_evidence(tenant_id,publication_id,evidence_id) VALUES (%s,%s,%s)',(tenant,publication_id,eid))
        for assertion in assertions:
            tx.execute('INSERT INTO publication_assertions(tenant_id,publication_id,assertion_id) VALUES (%s,%s,%s)',(tenant,publication_id,assertion['assertion_id']))
        existing=tx.execute('SELECT code FROM public_codes WHERE tenant_id=%s AND lot_key=%s',(tenant,lot['lot_key'])).fetchone()
        if existing:
            code=existing['code']
            if p.get('public_code') and p['public_code']!=code:
                raise DomainError(409,'stable_public_code','A lot already has a stable public code')
            tx.execute('UPDATE public_codes SET publication_id=%s,status=%s,revision=revision+1 WHERE tenant_id=%s AND lot_key=%s',(publication_id,'published',tenant,lot['lot_key']))
        else:
            code=p.get('public_code') or secrets.token_urlsafe(18)
            if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',code):
                raise DomainError(422,'invalid_public_code','Public code must be 8-100 URL-safe characters')
            tx.execute('INSERT INTO public_codes(code,tenant_id,lot_key,publication_id,status,revision) VALUES (%s,%s,%s,%s,%s,%s)',(code,tenant,lot['lot_key'],publication_id,'published',1))
        return {'id':publication_id,'lot_key':lot['lot_key'],'revision':revision,'public_code':code,'status':'published','content_hash':digest,'body':public_body}

    def _do_recall(self, tx, tenant, actor, p):
        root=self._lot(tx,tenant,p.get('lot_key'));reason=_text(p,'reason',maximum=2000)
        graph=self._lineage(tx,tenant,root['lot_key'],'downstream',30,2000)
        if graph['truncated']:
            raise DomainError(409,'recall_scope_truncated','Recall scope exceeds prototype traversal budget; no incomplete recall is committed')
        recall_id=_id()
        tx.execute('INSERT INTO recalls(tenant_id,id,origin_lot_key,reason,status,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)',(tenant,recall_id,root['lot_key'],reason,'active',_now(),str(actor['id'])))
        certain={root['lot_key']};changed=True
        while changed:
            changed=False
            for edge in graph['edges']:
                if edge['input_lot_key'] in certain and edge['allocation_status']=='known_source' and edge['output_lot_key'] not in certain:
                    certain.add(edge['output_lot_key']);changed=True
        affected=[]
        for lot in graph['nodes']:
            status='confirmed' if lot['lot_key'] in certain else 'possible'
            tx.execute('INSERT INTO recall_lots(tenant_id,recall_id,lot_key,scope_status) VALUES (%s,%s,%s,%s)',(tenant,recall_id,lot['lot_key'],status))
            affected.append({'lot_key':lot['lot_key'],'scope_status':status})
            for pub in tx.execute('SELECT id FROM publications WHERE tenant_id=%s AND lot_key=%s',(tenant,lot['lot_key'])).fetchall():
                self._invalidate_publication(tx,tenant,str(pub['id']),'recalled')
        return {'id':recall_id,'origin_lot_key':root['lot_key'],'status':'active','affected_lots':affected,'gaps':graph['gaps']}

    def _do_create_object_set(self, tx, tenant, actor, p):
        mode=p.get('mode','snapshot')
        if mode=='dynamic' and p.get('member_keys') is not None:
            raise DomainError(422,'object_set_mode','Dynamic object sets must use filters rather than fixed members')
        if mode not in {'dynamic','snapshot'}:
            raise DomainError(422,'invalid_mode','Object set mode must be dynamic or snapshot')
        filters=p.get('filter',{})
        if not isinstance(filters,dict) or set(filters)-{'entity_type','name_contains'}:
            raise DomainError(422,'unsupported_filter','Object set filter supports entity_type and name_contains')
        members=[]
        if mode=='snapshot':
            keys=p.get('member_keys')
            if keys is None:
                selection=self._entity_list(tx,tenant,dict(filters,limit=1000))
                if selection['truncated']:
                    raise DomainError(422,'object_set_limit','Snapshot filter exceeds member limit; refine the filter rather than silently truncating')
                keys=[x['entity_key'] for x in selection['items']]
            if not isinstance(keys,list) or len(keys)>1000:
                raise DomainError(422,'object_set_limit','Snapshot requires at most 1000 member keys')
            for key in dict.fromkeys(keys):
                entity=self._entity(tx,tenant,key)
                members.append({'entity_key':entity['entity_key'],'revision':entity['revision']})
        sid=_id()
        tx.execute('INSERT INTO object_sets(tenant_id,id,name,mode,filter_json,members,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,sid,_text(p,'name'),mode,_json(filters),_json(members),_now(),str(actor['id'])))
        return {'id':sid,'name':p['name'],'mode':mode,'filter':filters,'members':members}

    def public_trace(self, code):
        if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',code):
            raise DomainError(404,'public_trace_not_found','Published trace not found')
        with self.db.transaction() as tx:
            pointer=_unpack(tx.execute('SELECT * FROM public_codes WHERE code=%s',(code,)).fetchone())
            if not pointer:
                raise DomainError(404,'public_trace_not_found','Published trace not found')
            pub=_unpack(tx.execute('SELECT * FROM publications WHERE tenant_id=%s AND id=%s',(pointer['tenant_id'],pointer['publication_id'])).fetchone())
            status=pointer['status']
            if tx.execute('SELECT 1 FROM recalls r JOIN recall_lots l ON l.tenant_id=r.tenant_id AND l.recall_id=r.id WHERE l.tenant_id=%s AND l.lot_key=%s AND r.status=%s',(pointer['tenant_id'],pointer['lot_key'],'active')).fetchone():
                status='recalled'
            elif tx.execute('SELECT 1 FROM publication_evidence p JOIN evidence e ON e.tenant_id=p.tenant_id AND e.id=p.evidence_id WHERE p.tenant_id=%s AND p.publication_id=%s AND e.status<>%s',(pointer['tenant_id'],pointer['publication_id'],'active')).fetchone():
                status='withdrawn'
            elif tx.execute('SELECT 1 FROM publication_assertions p JOIN assertions a ON a.tenant_id=p.tenant_id AND a.id=p.assertion_id WHERE p.tenant_id=%s AND p.publication_id=%s AND a.status<>%s',(pointer['tenant_id'],pointer['publication_id'],'accepted')).fetchone():
                status='withdrawn'
            if status=='published':
                selected=[_unpack(item) for item in tx.execute('SELECT a.id,a.subject_key FROM publication_assertions p JOIN assertions a ON a.tenant_id=p.tenant_id AND a.id=p.assertion_id WHERE p.tenant_id=%s AND p.publication_id=%s',(pointer['tenant_id'],pointer['publication_id'])).fetchall()]
                selected_ids={item['id'] for item in selected}
                conflicts=self._assertion_conflicts(tx,pointer['tenant_id'],{item['subject_key'] for item in selected})
                if any(selected_ids.intersection(conflict['member_ids']) for conflict in conflicts):
                    # Fail closed for legacy imports or missed propagation; public reads do not rewrite history.
                    status='withdrawn'
            envelope={'public_code':code,'status':status,'revision':pub['revision'],'status_revision':pointer['revision'],'checked_at':_now(),'content_hash':pub['content_hash']}
            if status!='published':
                envelope['data']={'product':{'product_name':pub['body']['product']['product_name']},'quality_statements':[],'notice':'Current publication is recalled or withdrawn. Historical quality claims are unavailable as valid public statements.'}
            else:
                envelope['data']=pub['body']
            return envelope

    def _limit(self, params, default=100):
        try:
            value=int(params.get('limit',default))
        except (TypeError,ValueError):
            raise DomainError(422,'invalid_limit','limit must be an integer')
        if not 1<=value<=1000:
            raise DomainError(422,'invalid_limit','limit must be between 1 and 1000')
        return value

    def _list(self, tx, sql, args, params):
        limit=self._limit(params)
        raw_offset=params.get('offset',0)
        if isinstance(raw_offset,bool) or not (
            isinstance(raw_offset,int) or
            (isinstance(raw_offset,str) and re.fullmatch(r'[0-9]+',raw_offset))
        ):
            raise DomainError(422,'invalid_offset','offset must be a non-negative integer')
        offset=int(raw_offset)
        if not 0<=offset<=9223372036854775807:
            raise DomainError(422,'invalid_offset','offset must fit a non-negative signed 64-bit integer')
        rows=[_unpack(x) for x in tx.execute(sql+' LIMIT %s OFFSET %s',tuple(args)+(limit+1,offset)).fetchall()]
        more=len(rows)>limit
        return {'items':rows[:limit],'has_more':more,'truncated':more,'next_offset':offset+limit if more else None}

    def _entity_list(self, tx, tenant, p):
        sql='SELECT * FROM entities WHERE tenant_id=%s';args=[tenant]
        if p.get('entity_type'):
            sql+=' AND entity_type=%s';args.append(p['entity_type'])
        if p.get('name_contains'):
            sql+=' AND name LIKE %s';args.append('%'+str(p['name_contains']).replace('%','').replace('_','')+'%')
        return self._list(tx,sql+' ORDER BY created_at,entity_key',args,p)

    def _relation_list(self, tx, tenant, p):
        sql='SELECT * FROM relations WHERE tenant_id=%s';args=[tenant]
        if p.get('entity_key'):
            key=self._entity(tx,tenant,p['entity_key'])['entity_key'];sql+=' AND (subject_key=%s OR object_key=%s)';args.extend([key,key])
        if p.get('predicate_id'):
            sql+=' AND predicate_id=%s';args.append(p['predicate_id'])
        if p.get('dimension'):
            sql+=' AND dimension=%s';args.append(p['dimension'])
        status=p.get('status','accepted')
        if status!='all':
            if status not in {'candidate','accepted','rejected','needs_review'}:
                raise DomainError(422,'invalid_status','Unknown relation status')
            sql+=' AND status=%s';args.append(status)
        when=_time(p.get('valid_at',_now()),'valid_at')
        sql+=' AND valid_from<=%s AND (valid_to IS NULL OR valid_to>%s)';args.extend([when,when])
        return self._list(tx,sql+' ORDER BY created_at,id',args,p)

    def _graph(self, tx, tenant, p):
        root=self._entity(tx,tenant,p.get('entity_key') or p.get('start_key'))
        try:
            depth=int(p.get('depth',2));maximum=int(p.get('max_nodes',200))
        except (ValueError,TypeError):
            raise DomainError(422,'invalid_budget','Graph depth and max_nodes must be integers')
        if not 1<=depth<=5 or not 1<=maximum<=500:
            raise DomainError(422,'invalid_budget','Graph depth is 1-5 and max_nodes is 1-500')
        seen={root['entity_key']};edges={};frontier=[root['entity_key']];truncated=False
        for _ in range(depth):
            next_frontier=[]
            for key in frontier:
                page=self._relation_list(tx,tenant,dict(p,entity_key=key,limit=1000))
                truncated=truncated or page['has_more']
                for edge in page['items']:
                    other=edge['object_key'] if edge['subject_key']==key else edge['subject_key']
                    if other not in seen and len(seen)>=maximum:
                        truncated=True;continue
                    edges[edge['id']]=edge
                    if other not in seen:
                        seen.add(other);next_frontier.append(other)
            frontier=next_frontier
            if not frontier:
                break
        # Indicate a bounded view even when there are unexpanded neighbors.
        if frontier:
            for key in frontier:
                page=self._relation_list(tx,tenant,dict(p,entity_key=key,limit=1000))
                if any(x['id'] not in edges for x in page['items']):
                    truncated=True
        return {'nodes':[self._entity(tx,tenant,key) for key in sorted(seen)],'edges':list(edges.values()),'truncated':truncated,'gaps':[{'code':'query_budget'}] if truncated else [],'valid_at':p.get('valid_at',_now()),'semantics':'Qualified relation adjacency; not material ancestry or causal proof'}

    def _evidence_bundle(self, tx, tenant, p):
        entity=self._entity(tx,tenant,p.get('entity_key'))
        observations=[_unpack(x) for x in tx.execute('SELECT * FROM observations WHERE tenant_id=%s AND subject_key=%s ORDER BY observed_at LIMIT 1001',(tenant,entity['entity_key'])).fetchall()]
        assertions=[_unpack(x) for x in tx.execute('SELECT * FROM assertions WHERE tenant_id=%s AND subject_key=%s ORDER BY created_at LIMIT 1001',(tenant,entity['entity_key'])).fetchall()]
        truncated=len(observations)>1000 or len(assertions)>1000
        observations=observations[:1000];assertions=assertions[:1000]
        evidence_ids=set()
        for record in observations+assertions:
            evidence_ids.update(record['evidence_ids'])
        # Bounded individual reads keep all references tenant scoped.
        evidence=[]
        for eid in sorted(evidence_ids):
            evidence.extend(self._evidence(tx,tenant,[eid],active=False))
        statuses={e['id']:e['status'] for e in evidence}
        for record in observations:
            record['usable_for_inference']=all(statuses[e]=='active' for e in record['evidence_ids'])
        accepted=[];candidates=[]
        for record in assertions:
            if record['status']=='accepted' and all(statuses[e]=='active' for e in record['evidence_ids']):
                accepted.append(record)
            else:
                candidates.append(record)
        gaps=[{'code':'evidence_withdrawn','evidence_id':e['id']} for e in evidence if e['status']!='active']
        if truncated:gaps.append({'code':'query_truncated'})
        if not observations and not assertions:gaps.append({'code':'no_records'})
        content={'schema_version':'1.0.0','bundle_type':'EvidenceBundle','identity':entity,'observations':observations,'adopted_assertions':accepted,'candidate_assertions':candidates,'evidence':evidence,'gaps':gaps,'truncated':truncated,'retrieval_manifest':{'scope_entity_key':entity['entity_key'],'actual_premise_ids':[],'note':'Retrieved evidence is not automatically an adopted inference premise'},'generated_at':_now(),'limitations':['No statistical or causal conclusion is automatically established','A caller must register its actual adopted premises separately; inference execution registration is pending']}
        content['content_hash']=_hash(content)
        return content

    def query(self, action, tenant, actor, params=None):
        self._guard(tenant,actor,self.READ_ROLES)
        p=params or {}
        if not isinstance(p,dict):
            raise DomainError(422,'invalid_query','Query parameters must be an object')
        paged_actions={'packages','entities','relations','observations','assertions','events','lots','evidence','publications','recalls','object_sets','changes'}
        if 'offset' in p and (action not in paged_actions or
            (action=='events' and p.get('event_id')) or
            (action=='lots' and p.get('lot_key')) or
            (action=='evidence' and (p.get('evidence_id') or p.get('id')))):
            raise DomainError(422,'offset_not_supported','offset is only supported by ordinary resource lists')
        if p.get('known_at') or p.get('revision'):
            raise DomainError(422,'historical_snapshot_unsupported','Historical as-of reconstruction is not implemented; current state cannot impersonate an old snapshot')
        if p.get('valid_at') and action not in {'relations','graph'}:
            raise DomainError(422,'historical_snapshot_unsupported','Only relation validity filtering is currently implemented')
        with self.db.transaction() as tx:
            if action=='packages':
                return self._list(tx,'SELECT * FROM ontology_packages WHERE tenant_id=%s ORDER BY package_id,version',[tenant],p)
            if action=='entities':
                return self._entity_list(tx,tenant,p)
            if action=='entity':
                return self._entity(tx,tenant,p.get('entity_key') or p.get('id'))
            if action=='relations':
                return self._relation_list(tx,tenant,p)
            if action=='graph':
                return self._graph(tx,tenant,p)
            if action in {'observations','assertions'}:
                table=action;sql='SELECT * FROM '+table+' WHERE tenant_id=%s';args=[tenant]
                if p.get('entity_key'):
                    key=self._entity(tx,tenant,p['entity_key'])['entity_key'];sql+=' AND subject_key=%s';args.append(key)
                return self._list(tx,sql+' ORDER BY created_at,id',args,p)
            if action=='events':
                if p.get('event_id'):
                    row=_unpack(tx.execute('SELECT * FROM events WHERE tenant_id=%s AND id=%s',(tenant,_uuid(p['event_id']))).fetchone())
                    if not row:raise DomainError(404,'event_not_found','Event not found')
                    row['participants']=[_unpack(x) for x in tx.execute('SELECT * FROM event_participants WHERE tenant_id=%s AND event_id=%s',(tenant,row['id'])).fetchall()]
                    return row
                if p.get('entity_key'):
                    key=self._entity(tx,tenant,p['entity_key'])['entity_key']
                    return self._list(tx,'SELECT DISTINCT e.* FROM events e JOIN event_participants p ON p.tenant_id=e.tenant_id AND p.event_id=e.id WHERE e.tenant_id=%s AND p.entity_key=%s ORDER BY e.occurred_at,e.id',[tenant,key],p)
                return self._list(tx,'SELECT * FROM events WHERE tenant_id=%s ORDER BY occurred_at,id',[tenant],p)
            if action=='lots':
                if p.get('lot_key'):
                    return self._lot(tx,tenant,p['lot_key'])
                page=self._list(tx,'SELECT l.*,e.name,e.attributes FROM lots l JOIN entities e ON e.tenant_id=l.tenant_id AND e.entity_key=l.lot_key WHERE l.tenant_id=%s ORDER BY e.created_at,l.lot_key',[tenant],p)
                for row in page['items']:row['id']=row['lot_key'];row['entity_key']=row['lot_key']
                return page
            if action=='lineage':
                try:return self._lineage(tx,tenant,p.get('lot_key'),p.get('direction','upstream'),p.get('depth',10),p.get('max_nodes',200))
                except (TypeError,ValueError):raise DomainError(422,'invalid_budget','Lineage budgets must be integers')
            if action=='evidence':
                if p.get('evidence_id') or p.get('id'):
                    return self._evidence(tx,tenant,[p.get('evidence_id') or p.get('id')],active=False)[0]
                return self._list(tx,'SELECT * FROM evidence WHERE tenant_id=%s ORDER BY created_at,id',[tenant],p)
            if action=='evidence_bundle':
                return self._evidence_bundle(tx,tenant,p)
            if action=='trace_bundle':
                return self._trace_bundle(tx,tenant,p.get('lot_key'))
            if action=='publications':
                sql='SELECT p.*,c.code AS public_code FROM publications p LEFT JOIN public_codes c ON c.tenant_id=p.tenant_id AND c.lot_key=p.lot_key WHERE p.tenant_id=%s';args=[tenant]
                if p.get('lot_key'):
                    self._lot(tx,tenant,p['lot_key']);sql+=' AND p.lot_key=%s';args.append(p['lot_key'])
                return self._list(tx,sql+' ORDER BY p.created_at,p.id',args,p)
            if action=='recalls':
                return self._list(tx,'SELECT * FROM recalls WHERE tenant_id=%s ORDER BY created_at,id',[tenant],p)
            if action=='changes':
                if 'offset' in p:
                    raise DomainError(422,'cursor_only','Changes use a committed-event cursor; offset is not supported')
                cursor=p.get('cursor') or p.get('opaque_cursor');sequence=0
                if cursor:
                    try:
                        decoded=json.loads(base64.urlsafe_b64decode(str(cursor).encode()).decode())
                        if decoded['tenant']!=tenant:raise ValueError()
                        sequence=int(decoded['sequence'])
                        if sequence<0:raise ValueError()
                    except Exception:raise DomainError(422,'invalid_cursor','Cursor is invalid for this tenant')
                page=self._list(tx,'SELECT * FROM outbox WHERE tenant_id=%s AND sequence>%s ORDER BY sequence',[tenant,sequence],p)
                page.pop('next_offset',None)
                if page['items']:sequence=int(page['items'][-1]['sequence'])
                page['next_cursor']=base64.urlsafe_b64encode(_json({'tenant':tenant,'sequence':sequence}).encode()).decode()
                page['retention']='No deletion implemented in the prototype';page['delivery_semantics']='at_least_once'
                return page
            if action=='object_sets':
                sql='SELECT * FROM object_sets WHERE tenant_id=%s';args=[tenant]
                if p.get('id'):sql+=' AND id=%s';args.append(_uuid(p['id']))
                page=self._list(tx,sql+' ORDER BY created_at,id',args,p)
                for row in page['items']:
                    if row['mode']=='dynamic':
                        selection=self._entity_list(tx,tenant,dict(row['filter_json'],limit=1000))
                        row['current_members']=[{'entity_key':x['entity_key'],'revision':x['revision']} for x in selection['items']]
                        row['truncated']=selection['truncated']
                    else:
                        # Current tenant authorization still applies; historic members stay frozen.
                        for member in row['members']:self._entity(tx,tenant,member['entity_key'])
                return page
            if action=='action_types':
                return {'items':[{'action_id':name,'required_roles':sorted(roles),'execution_service':'Service.mutate','idempotency_required':True,'audit_required':True} for name,roles in self.ACTION_ROLES.items()]}
            if action=='stats':
                counts={}
                for table in ('entities','ontology_packages','evidence','observations','assertions','relations','events','lots','publications','recalls','object_sets','outbox'):
                    counts[table]=int(tx.execute('SELECT COUNT(*) AS count FROM '+table+' WHERE tenant_id=%s',(tenant,)).fetchone()['count'])
                return {'counts':counts,'backend':getattr(self.db,'backend','unknown'),'stage':'local_engineering_prototype','production_platform_connected':False,'field_validated':False,'limitations':['No automated quality release or product certification','No arbitrary domain rule execution or causal inference','Historical knowledge snapshots and event reversals pending','Write concurrency serialized per tenant; throughput not yet benchmarked']}
            raise DomainError(404,'unknown_query','Unsupported query action')
