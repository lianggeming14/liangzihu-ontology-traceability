"""Atomic manual receipts and non-inventory field events."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
from jsonschema import Draft202012Validator, FormatChecker
from .device_ingestion import DeviceService
from .service import DomainError, _id, _now, _json, _text, _time, _unpack, _hash

FIELD_EVENTS = {'inspection', 'irrigation', 'maintenance', 'incident'}

class FieldService(DeviceService):
    ACTION_ROLES = dict(DeviceService.ACTION_ROLES, ingest_manual={'admin', 'operator'})

    def __init__(self, db, asset_root=None):
        super().__init__(db)
        self.asset_root = Path(asset_root) if asset_root else Path(__file__).resolve().parents[1] / 'data' / 'assets'

    def _availability(self, tenant, evidence):
        if evidence['status'] != 'active': return 'withdrawn'
        metadata=evidence.get('metadata',{})
        asset=metadata.get('asset_key','')
        if evidence.get('uri','').startswith('asset://'):
            import re
            if not re.fullmatch('[0-9a-f]{64}',asset): return 'invalid_asset_reference'
            path=self.asset_root / hashlib.sha256(tenant.encode()).hexdigest() / asset
            digest=hashlib.sha256()
            try:
                if not path.is_file(): return 'missing'
                with path.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''): digest.update(block)
            except OSError:
                return 'unreadable'
            if digest.hexdigest()!=evidence['content_hash']: return 'hash_mismatch'
            processing=metadata.get('processing',{})
            if evidence['kind'] in {'image','video'} and processing.get('status')!='processed':
                return 'media_'+processing.get('status','not_checked')
            return 'verified'
        if metadata.get('receipt_format')=='manual-receipt/1':
            canonical=metadata.get('canonical_json','')
            if not isinstance(canonical,str) or hashlib.sha256(canonical.encode()).hexdigest()!=evidence['content_hash']:
                return 'hash_mismatch'
            if canonical!=_json(metadata.get('receipt')): return 'hash_mismatch'
            return 'verified'
        return 'reference_only'

    def _record(self, tx, tenant, key):
        record=super()._record(tx,tenant,key)
        if record:
            evidence=self._evidence(tx,tenant,record['evidence_ids'],active=False)
            record['evidence_availability']={e['id']:self._availability(tenant,e) for e in evidence}
            record['usable_for_inference']=bool(evidence) and all(v=='verified' for v in record['evidence_availability'].values())
        return record

    def _evidence_bundle(self,tx,tenant,p):
        bundle=super()._evidence_bundle(tx,tenant,p)
        key=bundle['identity']['entity_key']
        rows=tx.execute('SELECT id FROM device_records WHERE tenant_id=%s AND (device_entity_key=%s OR bound_entity_key=%s) ORDER BY captured_at DESC,id DESC LIMIT 201',(tenant,key,key)).fetchall()
        records=[self._record(tx,tenant,r['id']) for r in rows[:200]]
        evidence={e['id']:e for e in bundle['evidence']}
        for record in records:
            for item in self._evidence(tx,tenant,record['evidence_ids'],active=False): evidence[item['id']]=item
        for item in evidence.values(): item['availability']=self._availability(tenant,item)
        usable={eid:item['availability']=='verified' for eid,item in evidence.items()}
        for observation in bundle['observations']:
            observation['usable_for_inference']=bool(observation['evidence_ids']) and all(usable[eid] for eid in observation['evidence_ids'])
        accepted=[]
        for assertion in bundle['adopted_assertions']:
            if all(usable[eid] for eid in assertion['evidence_ids']): accepted.append(assertion)
            else: bundle['candidate_assertions'].append(assertion)
        bundle['adopted_assertions']=accepted
        bundle['device_records']=records
        bundle['evidence']=list(evidence.values())
        if records: bundle['gaps']=[g for g in bundle['gaps'] if g['code']!='no_records']
        if len(rows)>200:
            bundle['truncated']=True
            bundle['gaps'].append({'code':'device_records_truncated','limit':200})
        bundle['gaps'].extend({'code':'evidence_unavailable','evidence_id':e['id'],'availability':e['availability']} for e in evidence.values() if e['availability']!='verified')
        bundle['retrieval_manifest']['device_scope']='device_entity_key OR bound_entity_key within current tenant; receipts retain binding at capture'
        bundle['retrieval_manifest']['media_semantics']='technical inspection and receipt history only; no visual agricultural diagnosis or automatic adoption'
        bundle.pop('content_hash',None);bundle['content_hash']=_hash(bundle)
        return bundle

    def _do_ingest_manual(self, tx, tenant, actor, p):
        kind = p.get('record_kind')
        action = {'observation': 'create_observation', 'assertion': 'create_assertion', 'event': 'create_event'}.get(kind)
        if not action or not isinstance(p.get('payload'), dict):
            raise DomainError(422, 'invalid_manual_record', '请选择观测、陈述或现场事件并填写内容')
        note = _text(p, 'note', maximum=4000)
        source_id = _text(p, 'source_id', 'manual-form', maximum=200)
        body = deepcopy(p['payload'])
        body.setdefault('evidence_ids', [])
        if kind == 'observation':
            body['origin'] = 'reported'
            observed=_time(body.get('observed_at'),'observed_at')
            if datetime.fromisoformat(observed)>datetime.now(timezone.utc)+timedelta(minutes=5):
                raise DomainError(422,'future_observation','人工观测不能记录尚未发生的读数；预测请另作候选陈述')
        if kind == 'assertion': body['origin'] = 'manual'
        schemas = json.loads((Path(__file__).resolve().parents[1] / 'contracts' / 'input-schemas.json').read_text(encoding='utf-8'))
        issues = list(Draft202012Validator(schemas[action], format_checker=FormatChecker()).iter_errors(body))
        if issues:
            raise DomainError(422, 'schema_validation_failed', '人工填报内容不符合契约', [{'path': list(e.path), 'message': e.message} for e in issues[:10]])
        # Retain exactly the submitted envelope; hash covers these bytes, not a truth claim.
        raw = {'envelope': deepcopy(p), 'actor_id': str(actor['id']), 'tenant_id': tenant, 'recorded_at': _now()}
        canonical = _json(raw)
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        evidence = self._do_create_evidence(tx, tenant, actor, {
            'kind': 'manual', 'uri': 'urn:manual:sha256:' + digest,
            'content_hash': digest, 'source_id': source_id,
            'public_summary': '', 'metadata': {'receipt_format': 'manual-receipt/1',
                'receipt': raw, 'canonical_json': canonical, 'note': note}})
        body['evidence_ids'] = list(dict.fromkeys(body['evidence_ids'] + [evidence['id']]))
        record = getattr(self, '_do_' + action)(tx, tenant, actor, body)
        return {'id': record['id'], 'record_kind': kind, 'evidence': evidence, 'record': record}

    def _do_create_event(self, tx, tenant, actor, p):
        if p.get('event_type') not in FIELD_EVENTS:
            return super()._do_create_event(tx, tenant, actor, p)
        forbidden = {'inputs', 'outputs', 'items', 'loss_quantity', 'loss_unit', 'shipment_id', 'supersedes_id'} & set(p)
        if forbidden:
            raise DomainError(422, 'field_event_quantity', '现场记录不能修改库存或替代物料事件', sorted(forbidden))
        occurred = _time(p.get('occurred_at'), 'occurred_at')
        if datetime.fromisoformat(occurred)>datetime.now(timezone.utc)+timedelta(minutes=5):
            raise DomainError(422,'future_field_event','发生记录不能晚于服务器五分钟；未来采集请登记计划')
        evidence = self._evidence(tx, tenant, p.get('evidence_ids', []))
        participants = p.get('participants', [])
        if not isinstance(participants, list) or not 1 <= len(participants) <= 100:
            raise DomainError(422, 'field_participants', '现场事件需要至少一个关联对象，最多100个')
        resolved = []
        for participant in participants:
            entity = self._entity(tx, tenant, participant.get('entity_key'))
            role = _text(participant, 'role', maximum=100)
            if role in {'input','output','shipped_item','received_item'}:
                raise DomainError(422, 'reserved_role', '现场记录不能使用物料数量角色')
            resolved.append((entity['entity_key'], role))
        event_id = _id()
        body = dict(p, quantity_profile='not_applicable', field_record=True)
        eids = [x['id'] for x in evidence]
        tx.execute('INSERT INTO events(tenant_id,id,event_type,occurred_at,event_payload,evidence_ids,status,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', (tenant,event_id,p['event_type'],occurred,_json(body),_json(eids),'reported',_now(),str(actor['id'])))
        for key, role in dict.fromkeys(resolved):
            tx.execute('INSERT INTO event_participants(tenant_id,id,event_id,entity_key,role,quantity,unit) VALUES (%s,%s,%s,%s,%s,%s,%s)', (tenant,_id(),event_id,key,role,None,None))
        self._link_evidence(tx,tenant,eids,'event',event_id)
        return _unpack(tx.execute('SELECT * FROM events WHERE tenant_id=%s AND id=%s', (tenant,event_id)).fetchone())
