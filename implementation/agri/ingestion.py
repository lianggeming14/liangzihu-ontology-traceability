"""Modality-neutral receipt adapters. They do not infer quality or causation."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file
from jsonschema import Draft202012Validator, FormatChecker

SOURCE_KINDS = {'sensor', 'weather', 'image', 'video', 'remote_sensing', 'document', 'manual', 'official_api'}

def create_ingestion_blueprint(service, authenticate, base):
    bp = Blueprint('ingestion', __name__)
    schemas = json.loads((base / 'contracts' / 'input-schemas.json').read_text(encoding='utf-8'))
    validators = {name: Draft202012Validator(s, format_checker=FormatChecker()) for name, s in schemas.items()}

    def actor():
        from .service import DomainError
        value = authenticate()
        if not value or not value.get('tenant_id'):
            raise DomainError(401, 'authentication_required', '需要有效访问身份')
        return value

    def checked(action, body):
        from .service import DomainError
        errors = sorted(validators[action].iter_errors(body), key=lambda e: str(list(e.path)))
        if errors:
            raise DomainError(422, 'schema_validation_failed', '输入不符合数据契约',
                              [{'path': list(e.path), 'message': e.message} for e in errors[:10]])

    @bp.post('/api/v1/ingestion/records')
    def ingest_records():
        from .service import DomainError
        who = actor()
        envelope = request.get_json(silent=True)
        if not isinstance(envelope, dict) or envelope.get('source_kind') not in SOURCE_KINDS:
            raise DomainError(422, 'invalid_source_kind', '请选择登记的信源类别')
        records = envelope.get('records')
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise DomainError(422, 'invalid_records', '每次接入 1 至 100 条记录')
        base_key = request.headers.get('Idempotency-Key', '')
        if not base_key or len(base_key) > 150:
            raise DomainError(422, 'idempotency_key_required', '接入需要有效的 Idempotency-Key')
        receipts = []
        for index, record in enumerate(records):
            try:
                if not isinstance(record, dict):
                    raise DomainError(422, 'invalid_record', '每条记录必须为对象')
                kind = record.get('record_kind')
                body = copy.deepcopy(record.get('payload'))
                if not isinstance(body, dict):
                    raise DomainError(422, 'invalid_payload', 'payload 必须为对象')
                if kind == 'observation':
                    action = 'create_observation'
                    if envelope['source_kind'] in ('image', 'video', 'remote_sensing'):
                        body['origin'] = 'estimated'
                elif kind in ('assertion', 'forecast', 'model_candidate'):
                    action = 'create_assertion'
                    body['origin'] = 'forecast' if kind == 'forecast' else 'model' if kind == 'model_candidate' else body.get('origin', 'reported')
                elif kind == 'event':
                    action = 'create_event'
                else:
                    raise DomainError(422, 'invalid_record_kind', '不支持的标准记录类别')
                if not body.get('evidence_ids'):
                    raise DomainError(422, 'evidence_required', '接入记录必须引用已登记原始证据')
                checked(action, body)
                result = service.mutate(action, who['tenant_id'], who, body, base_key + ':' + str(index))
                receipts.append({'index': index, 'status': 'accepted', 'record_kind': kind, 'result': result})
            except DomainError as exc:
                receipts.append({'index': index, 'status': 'rejected', 'error': {'code': exc.code, 'message': exc.message, 'details': exc.details}})
        return jsonify({'data': {'source_kind': envelope['source_kind'], 'receipts': receipts,
                                 'transaction_scope': 'per_record', 'synthetic': bool(envelope.get('synthetic', False)),
                                 'accepted_count': sum(r['status'] == 'accepted' for r in receipts)}})

    @bp.post('/api/v1/ingestion/assets')
    def upload_asset():
        from .service import DomainError
        who = actor()
        if not set(who.get('roles', [])).intersection({'admin', 'operator'}):
            raise DomainError(403, 'role_denied', '当前角色不能上传原始材料')
        item = request.files.get('file')
        key = request.headers.get('Idempotency-Key', '')
        if item is None or not key or len(key) > 200:
            raise DomainError(422, 'invalid_asset', '需要 file 和 Idempotency-Key')
        kind = request.form.get('source_kind', 'document')
        if kind not in SOURCE_KINDS:
            raise DomainError(422, 'invalid_source_kind', '无效信源类别')
        content = item.read()
        if not content:
            raise DomainError(422, 'empty_asset', '不能上传空材料')
        digest = hashlib.sha256(content).hexdigest()
        tenant_dir = hashlib.sha256(who['tenant_id'].encode()).hexdigest()
        folder = base / 'data' / 'assets' / tenant_dir
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / digest
        original_name = Path(item.filename or 'asset').name[:200]
        evidence = {'kind': kind, 'uri': 'asset://' + digest, 'content_hash': digest,
                    'source_id': request.form.get('source_id', 'manual-upload'),
                    'public_summary': request.form.get('public_summary', ''),
                    'metadata': {'asset_key': digest, 'filename': original_name,
                                 'media_type': item.mimetype, 'size_bytes': len(content)}}
        checked('create_evidence', evidence)
        try:
            with path.open('xb') as stream:
                stream.write(content)
        except FileExistsError:
            pass
        result = service.mutate('create_evidence', who['tenant_id'], who, evidence, key)
        return jsonify({'data': result})

    return bp
