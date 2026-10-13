"""Generic, tenant-scoped device receipts and deterministic capture schedules.

This module receives evidence-backed camera/gate reports. It does not pull vendor
streams, operate gates, infer crop condition from images, or start a scheduler.
A capture slot is a plan; a received record retains its actual capture time.
"""
from datetime import datetime, timedelta, timezone
import json
import re

from .service import (Service, DomainError, _clean, _decimal, _hash, _id, _json,
                      _now, _text, _time, _unpack, _uuid)

DEVICE_ROLES = {'admin', 'operator'}
DEVICE_ACTIONS = {'register_device', 'create_capture_policy',
                  'set_capture_policy_status', 'ingest_device_record'}
DEVICE_QUERIES = {'devices', 'capture_policies', 'device_records', 'due_captures'}
RECORD_TYPES = {'camera_snapshot', 'camera_video', 'gate_status', 'manual_note'}


def _fields(data, allowed, required=()):
    if not isinstance(data, dict):
        raise DomainError(422, 'invalid_payload', '输入必须为对象')
    unknown = set(data) - set(allowed)
    missing = set(required) - set(data)
    if unknown or missing:
        raise DomainError(422, 'invalid_fields', '输入含未支持或缺少的字段',
                          {'unknown': sorted(unknown), 'missing': sorted(missing)})


def _integer(value, label, lower, upper):
    if isinstance(value, bool) or not (isinstance(value, int) or
            isinstance(value, str) and re.fullmatch(r'[0-9]+', value)):
        raise DomainError(422, 'invalid_integer', label + ' 必须为整数')
    value = int(value)
    if not lower <= value <= upper:
        raise DomainError(422, 'invalid_integer', label + ' 超出支持范围',
                          {'minimum': lower, 'maximum': upper})
    return value


def _dt(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)


def _aligned(at, anchor, interval):
    delta = at - anchor
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    return micros % (interval * 1000000) == 0


def _row(value):
    row = _unpack(value)
    if row is None:
        return None
    for key in ('focus_windows', 'observation_ids', 'data_json'):
        if key in row and isinstance(row[key], str):
            row[key] = json.loads(row[key])
    if 'data_json' in row:
        row['data'] = row.pop('data_json')
    if 'enabled' in row:
        row['enabled'] = bool(row['enabled'])
    return row


class DeviceService(Service):
    ACTION_ROLES = {**Service.ACTION_ROLES, **{a: DEVICE_ROLES for a in DEVICE_ACTIONS}}

    def _device(self, tx, tenant, key):
        row = _row(tx.execute('SELECT * FROM device_registrations WHERE tenant_id=%s AND id=%s',
                             (tenant, _uuid(key, 'device_id'))).fetchone())
        if row is None:
            raise DomainError(404, 'device_not_found', '设备不存在于当前租户')
        row['transport'] = 'generic_http_push'
        row['control_supported'] = False
        return row

    def _policy(self, tx, tenant, key):
        row = _row(tx.execute('SELECT * FROM capture_policies WHERE tenant_id=%s AND id=%s',
                             (tenant, _uuid(key, 'policy_id'))).fetchone())
        if row is None:
            raise DomainError(404, 'policy_not_found', '采集策略不存在于当前租户')
        return row

    def _do_register_device(self, tx, tenant, actor, p):
        _fields(p, {'name', 'device_kind', 'source_id', 'external_device_id',
                    'bound_entity_key', 'device_entity_key'},
                {'name', 'device_kind', 'source_id', 'external_device_id', 'bound_entity_key'})
        kind = p['device_kind']
        if not isinstance(kind, str) or kind not in {'camera', 'gate'}:
            raise DomainError(422, 'invalid_device_kind', '设备类型仅支持 camera 或 gate')
        bound = self._entity(tx, tenant, p['bound_entity_key'])
        name = _text(p, 'name', maximum=200)
        source = _text(p, 'source_id', maximum=200)
        external = _text(p, 'external_device_id', maximum=200)
        if tx.execute('SELECT 1 FROM device_registrations WHERE tenant_id=%s AND source_id=%s AND external_device_id=%s',
                      (tenant, source, external)).fetchone():
            raise DomainError(409, 'device_identity_conflict', '该信源中的设备标识已登记；不能按名称合并')
        if p.get('device_entity_key'):
            entity = self._entity(tx, tenant, p['device_entity_key'])
            if entity['entity_type'] != 'device':
                raise DomainError(422, 'invalid_device_entity', '设备必须绑定 device 身份类型')
        else:
            entity = self._do_create_entity(tx, tenant, actor, {
                'entity_type': 'device', 'name': name,
                'attrs': {'device_kind': kind, 'source_id': source, 'external_device_id': external}})
        if entity['entity_key'] == bound['entity_key']:
            raise DomainError(422, 'self_binding', '设备不能将自己作为被监测对象')
        key = _id()
        tx.execute('INSERT INTO device_registrations(tenant_id,id,name,device_kind,source_id,external_device_id,device_entity_key,bound_entity_key,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (tenant, key, name, kind, source, external, entity['entity_key'], bound['entity_key'], _now(), str(actor['id'])))
        return self._device(tx, tenant, key)

    def _record_type(self, device, kind, manual=True):
        expected = {'camera_snapshot', 'camera_video'} if device['device_kind'] == 'camera' else {'gate_status'}
        if manual:
            expected.add('manual_note')
        if not isinstance(kind, str) or kind not in expected:
            raise DomainError(422, 'incompatible_record_type', '记录类别与设备类别不匹配')
        return kind

    def _do_create_capture_policy(self, tx, tenant, actor, p):
        _fields(p, {'device_id', 'name', 'record_type', 'start_at', 'end_at',
                    'interval_seconds', 'focus_windows'},
                {'device_id', 'name', 'record_type', 'start_at', 'interval_seconds'})
        device = self._device(tx, tenant, p['device_id'])
        kind = self._record_type(device, p['record_type'], manual=False)
        start = _time(p['start_at'], 'start_at')
        end = _time(p.get('end_at'), 'end_at', optional=True)
        if end is not None and _dt(end) <= _dt(start):
            raise DomainError(422, 'invalid_time_range', 'end_at 必须晚于 start_at，区间采用左闭右开')
        interval = _integer(p['interval_seconds'], 'interval_seconds', 60, 604800)
        windows = p.get('focus_windows', [])
        if not isinstance(windows, list) or len(windows) > 20:
            raise DomainError(422, 'invalid_focus_windows', '每个策略最多 20 个重点窗口')
        normalized = []
        for window in windows:
            _fields(window, {'start_at', 'end_at', 'interval_seconds', 'label'},
                    {'start_at', 'end_at', 'interval_seconds', 'label'})
            begin = _time(window['start_at'], 'focus.start_at')
            finish = _time(window['end_at'], 'focus.end_at')
            if not (_dt(start) <= _dt(begin) < _dt(finish)) or end and _dt(finish) > _dt(end):
                raise DomainError(422, 'invalid_focus_range', '重点窗口必须位于策略有效区间内')
            seconds = _integer(window['interval_seconds'], 'focus.interval_seconds', 60, min(interval, 86400))
            normalized.append({'start_at': begin, 'end_at': finish, 'interval_seconds': seconds,
                               'label': _text(window, 'label', maximum=200)})
        key = _id()
        tx.execute('INSERT INTO capture_policies(tenant_id,id,device_id,name,record_type,start_at,end_at,interval_seconds,focus_windows,enabled,revision,created_at,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (tenant, key, device['id'], _text(p, 'name', maximum=200), kind, start, end,
                    interval, _json(normalized), True, 1, _now(), str(actor['id'])))
        return self._policy(tx, tenant, key)

    def _do_set_capture_policy_status(self, tx, tenant, actor, p):
        _fields(p, {'policy_id', 'enabled'}, {'policy_id', 'enabled'})
        policy = self._policy(tx, tenant, p['policy_id'])
        if not isinstance(p['enabled'], bool):
            raise DomainError(422, 'invalid_enabled', 'enabled 必须为布尔值')
        if policy['enabled'] != p['enabled']:
            tx.execute('UPDATE capture_policies SET enabled=%s,revision=revision+1 WHERE tenant_id=%s AND id=%s',
                       (p['enabled'], tenant, policy['id']))
        return self._policy(tx, tenant, policy['id'])

    @staticmethod
    def _slot(policy, when):
        at = _dt(when)
        start = _dt(policy['start_at'])
        if at < start or policy['end_at'] and at >= _dt(policy['end_at']):
            return None
        valid = _aligned(at, start, policy['interval_seconds'])
        labels = []
        for window in policy['focus_windows']:
            begin, end = _dt(window['start_at']), _dt(window['end_at'])
            if begin <= at < end:
                labels.append(window['label'])
                valid = valid or _aligned(at, begin, window['interval_seconds'])
        if not valid:
            return None
        canonical = at.isoformat()
        return {'slot_id': _hash({'policy_id': policy['id'], 'slot_at': canonical}),
                'slot_at': canonical, 'policy_id': policy['id'], 'device_id': policy['device_id'],
                'record_type': policy['record_type'], 'priority': 'focus' if labels else 'routine',
                'focus_labels': sorted(set(labels))}

    def _record(self, tx, tenant, key):
        row = _row(tx.execute('SELECT * FROM device_records WHERE tenant_id=%s AND id=%s',
                             (tenant, key)).fetchone())
        if row is not None:
            evidence = self._evidence(tx, tenant, row['evidence_ids'], active=False)
            row['evidence_status'] = 'active' if all(x['status'] == 'active' for x in evidence) else 'withdrawn'
            # A database reference alone does not prove the original bytes are
            # available. FieldService supplies the configured asset verification.
            row['evidence_availability'] = {e['id']: 'not_checked' if e['status'] == 'active' else 'withdrawn' for e in evidence}
            row['usable_for_inference'] = False
            row['epistemic_status'] = 'reported'
        return row

    def _do_ingest_device_record(self, tx, tenant, actor, p):
        _fields(p, {'device_id', 'source_record_id', 'record_type', 'captured_at', 'evidence_ids',
                    'priority', 'note', 'data', 'policy_id', 'slot_at'},
                {'device_id', 'source_record_id', 'record_type', 'captured_at', 'evidence_ids', 'data'})
        device = self._device(tx, tenant, p['device_id'])
        kind = self._record_type(device, p['record_type'])
        when = _time(p['captured_at'], 'captured_at')
        if _dt(when) > _dt(_now()) + timedelta(minutes=5):
            raise DomainError(422, 'future_capture', '实际采集时间不能超前服务器超过五分钟')
        source_record = _text(p, 'source_record_id', maximum=200)
        note = p.get('note', '')
        if not isinstance(note, str) or len(note) > 4000:
            raise DomainError(422, 'invalid_note', 'note 必须为不超过 4000 字符的文本')
        if kind == 'manual_note' and not note.strip():
            raise DomainError(422, 'note_required', '手动重点记录必须填写说明')
        data = p['data']
        if kind == 'gate_status':
            _fields(data, {'state', 'position_pct'}, {'state'})
            if not isinstance(data['state'], str) or data['state'] not in {'open', 'closed', 'partial', 'unknown'}:
                raise DomainError(422, 'invalid_gate_state', '闸门状态必须为 open/closed/partial/unknown')
            data = dict(data)
            if 'position_pct' in data:
                position = _decimal(data['position_pct'], 'position_pct', zero=True)
                if position > 100 or (data['state'] == 'open' and position != 100) or (data['state'] == 'closed' and position != 0) or (data['state'] == 'partial' and not 0 < position < 100):
                    raise DomainError(422, 'invalid_gate_position', '开度必须在 0 至 100%，并与状态一致')
                data['position_pct'] = str(position)
        elif kind == 'manual_note':
            _fields(data, set())
        else:
            _fields(data, {'duration_seconds'})
            data = dict(data)
            if 'duration_seconds' in data:
                duration = _decimal(data['duration_seconds'], 'duration_seconds')
                if duration > 86400:
                    raise DomainError(422, 'invalid_duration', '媒体时长不能超过 86400 秒')
                data['duration_seconds'] = str(duration)
        policy, slot = None, None
        if ('policy_id' in p) != ('slot_at' in p):
            raise DomainError(422, 'incomplete_slot', 'policy_id 与 slot_at 必须同时提供')
        if 'policy_id' in p:
            policy = self._policy(tx, tenant, p['policy_id'])
            if policy['device_id'] != device['id'] or policy['record_type'] != kind:
                raise DomainError(422, 'incompatible_slot', '策略、设备与记录类型必须一致')
            slot = self._slot(policy, _time(p['slot_at'], 'slot_at'))
            if slot is None or _dt(when) < _dt(slot['slot_at']) - timedelta(seconds=5):
                raise DomainError(422, 'invalid_slot', 'slot_at 必须为策略的有效时点，实际采集不能早于该时点')
        priority = p.get('priority', slot['priority'] if slot else 'routine')
        if not isinstance(priority, str) or priority not in {'routine', 'focus'} or slot and priority != slot['priority']:
            raise DomainError(422, 'invalid_priority', 'priority 必须为 routine/focus，并与采集槽一致')
        if not isinstance(p['evidence_ids'], list) or not 1 <= len(p['evidence_ids']) <= 100:
            raise DomainError(422, 'evidence_required', '记录必须关联 1 至 100 条原始证据')
        ids = sorted(set(_uuid(v, 'evidence_id') for v in p['evidence_ids']))
        normalized = {'device_id': device['id'], 'source_record_id': source_record, 'record_type': kind,
                      'captured_at': when, 'data': data, 'note': note, 'priority': priority,
                      'evidence_ids': ids, 'policy_id': policy['id'] if policy else None,
                      'slot_at': slot['slot_at'] if slot else None}
        digest = _hash(normalized)
        old = _row(tx.execute('SELECT * FROM device_records WHERE tenant_id=%s AND device_id=%s AND source_record_id=%s',
                             (tenant, device['id'], source_record)).fetchone())
        if old:
            if old['payload_hash'] != digest:
                raise DomainError(409, 'source_record_conflict', '相同信源记录标识出现不同内容；保留原件并拒绝覆盖')
            return self._record(tx, tenant, old['id'])
        evidence = self._evidence(tx, tenant, ids)
        if kind in {'camera_snapshot', 'camera_video'}:
            expected = 'image' if kind == 'camera_snapshot' else 'video'
            if not any(e['kind'] == expected for e in evidence):
                raise DomainError(422, 'media_evidence_required', '摄像头记录必须关联对应 image/video 原始证据')
        if slot:
            prior = tx.execute('SELECT id FROM device_records WHERE tenant_id=%s AND slot_id=%s',
                               (tenant, slot['slot_id'])).fetchone()
            if prior:
                raise DomainError(409, 'slot_already_received', '该计划时点已有记录；重试应保留原 source_record_id')
            if not policy['enabled']:
                raise DomainError(409, 'policy_disabled', '已暂停策略不能接收新的计划记录；可另记手动记录')
        observations = []
        if kind == 'gate_status':
            values = [('gate.state', {'value': data['state'], 'unit': '1'})]
            if 'position_pct' in data:
                values.append(('gate.position_pct', {'value': data['position_pct'], 'unit': '%'}))
            for property_id, value in values:
                result = self._do_create_observation(tx, tenant, actor, {
                    'subject_key': device['device_entity_key'], 'property_id': property_id,
                    'value': value, 'observed_at': when, 'method': 'generic_http_push',
                    'origin': 'reported', 'evidence_ids': ids,
                    'spatial_context': {'bound_entity_key': device['bound_entity_key'], 'source_record_id': source_record}})
                observations.append(result['id'])
        key = _id()
        tx.execute('INSERT INTO device_records(tenant_id,id,device_id,source_record_id,record_type,captured_at,received_at,device_entity_key,bound_entity_key,priority,note,data_json,evidence_ids,observation_ids,policy_id,slot_at,slot_id,payload_hash,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (tenant, key, device['id'], source_record, kind, when, _now(), device['device_entity_key'],
                    device['bound_entity_key'], priority, note, _json(data), _json(ids), _json(observations),
                    policy['id'] if policy else None, slot['slot_at'] if slot else None,
                    slot['slot_id'] if slot else None, digest, str(actor['id'])))
        self._link_evidence(tx, tenant, ids, 'device_record', key)
        return self._record(tx, tenant, key)

    def query(self, action, tenant, actor, params=None):
        if action not in DEVICE_QUERIES:
            return super().query(action, tenant, actor, params)
        self._guard(tenant, actor, self.READ_ROLES)
        p = params or {}
        common = {'limit', 'offset'}
        allowed = {
            'devices': common | {'id', 'device_kind', 'bound_entity_key'},
            'capture_policies': common | {'id', 'device_id'},
            'device_records': common | {'id', 'device_id', 'record_type'},
            'due_captures': common | {'device_id', 'since', 'as_of'},
        }[action]
        _fields(p, allowed)
        limit = _integer(p.get('limit', 100), 'limit', 1, 500)
        offset = _integer(p.get('offset', 0), 'offset', 0, 9223372036854775807)
        with self.db.transaction() as tx:
            if action == 'due_captures':
                return self._due(tx, tenant, p, limit, offset)
            table = {'devices': 'device_registrations', 'capture_policies': 'capture_policies',
                     'device_records': 'device_records'}[action]
            sql, values = 'SELECT * FROM ' + table + ' WHERE tenant_id=%s', [tenant]
            if p.get('id') is not None:
                sql += ' AND id=%s'; values.append(_uuid(p['id']))
            if 'device_id' in p:
                device = self._device(tx, tenant, p['device_id'])
                sql += ' AND device_id=%s'; values.append(device['id'])
            if 'bound_entity_key' in p:
                entity = self._entity(tx, tenant, p['bound_entity_key'])
                sql += ' AND bound_entity_key=%s'; values.append(entity['entity_key'])
            if 'device_kind' in p:
                if not isinstance(p['device_kind'], str) or p['device_kind'] not in {'camera', 'gate'}:
                    raise DomainError(422, 'invalid_device_kind', '无效设备类型')
                sql += ' AND device_kind=%s'; values.append(p['device_kind'])
            if 'record_type' in p:
                if not isinstance(p['record_type'], str) or p['record_type'] not in RECORD_TYPES:
                    raise DomainError(422, 'invalid_record_type', '无效记录类型')
                sql += ' AND record_type=%s'; values.append(p['record_type'])
            order = 'captured_at,id' if action == 'device_records' else 'created_at,id'
            rows = tx.execute(sql + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s',
                              tuple(values) + (limit + 1, offset)).fetchall()
            more = len(rows) > limit
            items = [_row(r) for r in rows[:limit]]
            if action == 'device_records':
                items = [self._record(tx, tenant, r['id']) for r in items]
            elif action == 'devices':
                items = [dict(r, transport='generic_http_push', control_supported=False) for r in items]
            return {'items': items, 'has_more': more, 'truncated': more,
                    'next_offset': offset + limit if more else None}

    def _due(self, tx, tenant, p, limit, offset):
        since = _time(p.get('since'), 'since')
        as_of = _time(p.get('as_of', _now()), 'as_of')
        begin, end = _dt(since), _dt(as_of)
        if not begin <= end or end - begin > timedelta(days=7):
            raise DomainError(422, 'invalid_planning_range', '计划查询范围必须递增且不超过七天')
        if end > _dt(_now()) + timedelta(minutes=5):
            raise DomainError(422, 'future_due', '到期计划的 as_of 不能超前服务器超过五分钟')
        sql = 'SELECT * FROM capture_policies WHERE tenant_id=%s AND enabled=%s'
        values = [tenant, True]
        if 'device_id' in p:
            device = self._device(tx, tenant, p['device_id'])
            sql += ' AND device_id=%s'; values.append(device['id'])
        rows = tx.execute(sql + ' ORDER BY id LIMIT 501', tuple(values)).fetchall()
        if len(rows) > 500:
            raise DomainError(422, 'planning_budget', '策略数量超过 500，请按设备分批查询')
        slots = {}
        for row in rows:
            policy = _row(row)
            streams = [{'start_at': policy['start_at'], 'end_at': policy['end_at'],
                        'interval_seconds': policy['interval_seconds']}, *policy['focus_windows']]
            for stream in streams:
                anchor = _dt(stream['start_at'])
                lower = max(begin, anchor)
                upper = min(end, _dt(stream['end_at'])) if stream.get('end_at') else end
                delta = lower - anchor
                # Exact microsecond arithmetic avoids floating-point slot drift.
                elapsed = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
                step = stream['interval_seconds'] * 1000000
                number = (elapsed + step - 1) // step
                at = anchor + timedelta(seconds=number * stream['interval_seconds'])
                while at <= upper:
                    if stream.get('end_at') and at >= _dt(stream['end_at']):
                        break
                    slot = self._slot(policy, at.isoformat())
                    if slot:
                        slots[slot['slot_id']] = slot
                        if len(slots) > 10000:
                            raise DomainError(422, 'planning_budget', '计划时点超过 10000，请缩短查询时间或按设备查询')
                    at += timedelta(seconds=stream['interval_seconds'])
        received = set()
        for row in tx.execute('SELECT slot_id FROM device_records WHERE tenant_id=%s AND slot_at>=%s AND slot_at<=%s',
                              (tenant, since, as_of)).fetchall():
            if row['slot_id']:
                received.add(row['slot_id'])
        items = sorted((slot for key, slot in slots.items() if key not in received),
                       key=lambda x: (x['slot_at'], x['policy_id']))
        page = items[offset:offset + limit]
        more = offset + limit < len(items)
        return {'items': page, 'has_more': more, 'truncated': more,
                'next_offset': offset + limit if more else None, 'since': since, 'as_of': as_of,
                'total_pending': len(items), 'execution_status': 'planning_only',
                'schedule_semantics': 'UTC anchored periodic/window union; duplicate timestamps merged; windows are [start,end); focus takes priority',
                'notice': '仅返回未收到记录的计划时点；不表示设备在线或已抓拍，也不执行闸门控制。分页期间接入记录可能改变待采集集合。'}


# These public schemas are imported by the HTTP and OpenAPI layers. Service-side
# checks remain authoritative for cross-record, quantity and temporal invariants.
_UUID_SCHEMA = {'type': 'string', 'format': 'uuid'}
_TIME_SCHEMA = {'type': 'string', 'format': 'date-time', 'maxLength': 100}
_NAME_SCHEMA = {'type': 'string', 'minLength': 1, 'maxLength': 200}
_DECIMAL_SCHEMA = {'type': 'string', 'pattern': r'^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,9})?$'}


def _object_schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required,
            'additionalProperties': False}


DEVICE_SCHEMAS = {
    'register_device': _object_schema({
        'name': _NAME_SCHEMA, 'device_kind': {'enum': ['camera', 'gate']},
        'source_id': _NAME_SCHEMA, 'external_device_id': _NAME_SCHEMA,
        'bound_entity_key': _UUID_SCHEMA, 'device_entity_key': _UUID_SCHEMA,
    }, ['name', 'device_kind', 'source_id', 'external_device_id', 'bound_entity_key']),
    'create_capture_policy': _object_schema({
        'device_id': _UUID_SCHEMA, 'name': _NAME_SCHEMA,
        'record_type': {'enum': ['camera_snapshot', 'camera_video', 'gate_status']},
        'start_at': _TIME_SCHEMA, 'end_at': _TIME_SCHEMA,
        'interval_seconds': {'type': 'integer', 'minimum': 60, 'maximum': 604800},
        'focus_windows': {'type': 'array', 'maxItems': 20, 'items': _object_schema({
            'start_at': _TIME_SCHEMA, 'end_at': _TIME_SCHEMA, 'label': _NAME_SCHEMA,
            'interval_seconds': {'type': 'integer', 'minimum': 60, 'maximum': 86400},
        }, ['start_at', 'end_at', 'interval_seconds', 'label'])},
    }, ['device_id', 'name', 'record_type', 'start_at', 'interval_seconds']),
    'set_capture_policy_status': _object_schema({
        'policy_id': _UUID_SCHEMA, 'enabled': {'type': 'boolean'},
    }, ['policy_id', 'enabled']),
    'ingest_device_record': _object_schema({
        'device_id': _UUID_SCHEMA, 'source_record_id': _NAME_SCHEMA,
        'record_type': {'enum': sorted(RECORD_TYPES)}, 'captured_at': _TIME_SCHEMA,
        'evidence_ids': {'type': 'array', 'items': _UUID_SCHEMA, 'minItems': 1, 'maxItems': 100, 'uniqueItems': True},
        'data': {'type': 'object'}, 'priority': {'enum': ['routine', 'focus']},
        'note': {'type': 'string', 'maxLength': 4000},
        'policy_id': _UUID_SCHEMA, 'slot_at': _TIME_SCHEMA,
    }, ['device_id', 'source_record_id', 'record_type', 'captured_at', 'evidence_ids', 'data']),
}
DEVICE_SCHEMAS['ingest_device_record'].update({
    'dependentRequired': {'policy_id': ['slot_at'], 'slot_at': ['policy_id']},
    'allOf': [
        {'if': {'properties': {'record_type': {'const': 'gate_status'}}},
         'then': {'properties': {'data': _object_schema({
             'state': {'enum': ['open', 'closed', 'partial', 'unknown']},
             'position_pct': _DECIMAL_SCHEMA,
         }, ['state'])}}},
        {'if': {'properties': {'record_type': {'const': 'manual_note'}}},
         'then': {'required': ['note'], 'properties': {
             'note': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
             'data': _object_schema({}, []),
         }}},
        {'if': {'properties': {'record_type': {'enum': ['camera_snapshot', 'camera_video']}}},
         'then': {'properties': {'data': _object_schema({'duration_seconds': _DECIMAL_SCHEMA}, [])}}},
    ],
})
