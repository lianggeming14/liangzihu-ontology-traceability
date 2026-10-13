"""Synthetic device ingestion tests; SQLite is not the PostgreSQL acceptance gate."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from agri.device_ingestion import DeviceService, DEVICE_SCHEMAS
from agri.service import DomainError

TENANT = 'device-test-a'
ACTOR = {'id': 'synthetic-device-operator', 'tenant_id': TENANT, 'roles': ['admin']}
START = '2026-10-01T00:00:00+00:00'


@pytest.fixture
def devices(database):
    return DeviceService(database)


def mutate(service, action, body, key=None, tenant=TENANT, actor=None):
    return service.mutate(action, tenant, actor or {**ACTOR, 'tenant_id': tenant}, body, key or str(uuid4()))


def query(service, action, params=None, tenant=TENANT):
    return service.query(action, tenant, {**ACTOR, 'tenant_id': tenant}, params or {})


def field(service, tenant=TENANT):
    return mutate(service, 'create_entity', {'entity_type': 'field', 'name': '合成监测田块'}, tenant=tenant)['entity_key']


def evidence(service, kind='official_api', tenant=TENANT):
    return mutate(service, 'create_evidence', {'kind': kind, 'uri': 'asset://' + 'a' * 64,
                   'content_hash': 'a' * 64, 'source_id': 'synthetic-device-http',
                   'metadata': {'synthetic': True}}, tenant=tenant)['id']


def register(service, kind='camera', bound=None, external=None, tenant=TENANT):
    return mutate(service, 'register_device', {'name': '合成' + kind, 'device_kind': kind,
                  'source_id': 'synthetic-device-http', 'external_device_id': external or str(uuid4()),
                  'bound_entity_key': bound or field(service, tenant)}, tenant=tenant)


def policy(service, device, **changes):
    body = {'device_id': device['id'], 'name': '合成采集计划',
            'record_type': 'camera_snapshot' if device['device_kind'] == 'camera' else 'gate_status',
            'start_at': START, 'end_at': '2026-10-01T00:10:00+00:00', 'interval_seconds': 300,
            'focus_windows': [
                {'start_at': '2026-10-01T00:01:00Z', 'end_at': '2026-10-01T00:04:00Z', 'interval_seconds': 60, 'label': '投饵前后'},
                {'start_at': '2026-10-01T00:02:00Z', 'end_at': '2026-10-01T00:04:00Z', 'interval_seconds': 60, 'label': '人工关注'},
            ]}
    body.update(changes)
    return mutate(service, 'create_capture_policy', body)


def gate_record(device, ev, **changes):
    body = {'device_id': device['id'], 'source_record_id': 'upstream-record-1', 'record_type': 'gate_status',
            'captured_at': START, 'evidence_ids': [ev], 'data': {'state': 'partial', 'position_pct': '25.50'}}
    body.update(changes)
    return body


def count(service, table):
    assert table in {'device_records', 'device_registrations', 'observations', 'outbox', 'audit_log', 'idempotency', 'entities', 'capture_policies'}
    with service.db.transaction() as tx:
        return tx.execute('SELECT COUNT(*) AS n FROM ' + table + ' WHERE tenant_id=%s', (TENANT,)).fetchone()['n']


def test_registration_stable_source_identity_binding_and_tenant_isolation(devices):
    bound = field(devices)
    first = register(devices, bound=bound, external='camera-01')
    second = register(devices, bound=bound, external='camera-02')
    assert first['id'] != second['id']
    assert first['device_entity_key'] != second['device_entity_key']
    assert first['bound_entity_key'] == bound
    assert first['control_supported'] is False
    assert query(devices, 'entity', {'entity_key': first['device_entity_key']})['entity_type'] == 'device'
    before = count(devices, 'entities')
    with pytest.raises(DomainError, match='已登记'):
        register(devices, bound=bound, external='camera-01')
    assert count(devices, 'entities') == before
    foreign = register(devices, tenant='device-test-b', external='camera-01')
    assert foreign['id'] != first['id']
    with pytest.raises(DomainError) as caught:
        policy(devices, foreign)
    assert caught.value.status == 404
    assert query(devices, 'devices', {'bound_entity_key': bound})['items'][0]['bound_entity_key'] == bound
    viewer = {**ACTOR, 'roles': ['viewer']}
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'register_device', {'name': '禁止', 'device_kind': 'camera', 'source_id': 's',
               'external_device_id': 'e', 'bound_entity_key': bound}, actor=viewer)
    assert caught.value.status == 403


def test_gate_receipt_idempotency_atomic_reported_observations_and_source_conflict(devices):
    gate, ev = register(devices, 'gate'), evidence(devices)
    body = gate_record(gate, ev)
    before = {t: count(devices, t) for t in ('outbox', 'audit_log')}
    first = mutate(devices, 'ingest_device_record', body, key='gate-report-key')
    assert mutate(devices, 'ingest_device_record', body, key='gate-report-key') == first
    assert mutate(devices, 'ingest_device_record', body)['id'] == first['id']
    assert count(devices, 'device_records') == 1
    assert count(devices, 'observations') == 2
    observations = query(devices, 'observations', {'subject_key': gate['device_entity_key']})['items']
    assert {o['origin'] for o in observations} == {'reported'}
    assert {o['subject_key'] for o in observations} == {gate['device_entity_key']}
    assert first['captured_at'] != first['received_at']
    assert first['usable_for_inference'] is False  # database-only service has not inspected asset bytes
    assert set(first['evidence_availability'].values()) == {'not_checked'}
    assert first['bound_entity_key'] == gate['bound_entity_key']
    assert count(devices, 'audit_log') == before['audit_log'] + 2  # fresh request key is a separate audit
    assert count(devices, 'outbox') == before['outbox'] + 2
    changed = deepcopy(body)
    changed['data']['position_pct'] = '30'
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'ingest_device_record', changed)
    assert caught.value.code == 'source_record_conflict'
    assert count(devices, 'observations') == 2
    assert query(devices, 'device_records')['items'][0]['data']['position_pct'] == '25.50'


def test_parallel_redelivery_creates_one_receipt_and_one_observation_pair(devices):
    gate, ev = register(devices, 'gate'), evidence(devices)
    body = gate_record(gate, ev)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda n: mutate(devices, 'ingest_device_record', body, key='parallel-' + str(n)), range(2)))
    assert results[0]['id'] == results[1]['id']
    assert count(devices, 'device_records') == 1
    assert count(devices, 'observations') == 2


def test_foreign_evidence_rejection_rolls_back_receipt_observations_and_idempotency(devices):
    gate = register(devices, 'gate')
    foreign_ev = evidence(devices, tenant='device-test-b')
    before = {t: count(devices, t) for t in ('device_records', 'observations', 'outbox', 'audit_log', 'idempotency')}
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'ingest_device_record', gate_record(gate, foreign_ev), key='failed-receipt')
    assert caught.value.status == 404
    assert {t: count(devices, t) for t in before} == before


@pytest.mark.parametrize('changes', [
    {'data': {'state': 'partial', 'position_pct': 0.5}},
    {'data': {'state': 'open', 'position_pct': '0'}},
    {'data': {'state': 'partial', 'position_pct': '101'}},
    {'data': {'state': ['open']}},
    {'data': {'state': 'open', 'control_command': 'open'}},
    {'captured_at': '2026-10-01T00:00:00'},
    {'captured_at': '2999-01-01T00:00:00Z'},
    {'record_type': 'camera_snapshot'},
])
def test_gate_rejects_invalid_quantity_enum_time_or_control_fields(devices, changes):
    gate, ev = register(devices, 'gate'), evidence(devices)
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'ingest_device_record', gate_record(gate, ev, **changes))
    assert caught.value.status == 422
    assert count(devices, 'device_records') == 0
    assert count(devices, 'observations') == 0


def test_focus_window_slots_have_defined_boundaries_deduplicate_and_resume(devices):
    camera, ev = register(devices), evidence(devices, 'image')
    plan = policy(devices, camera)
    params = {'device_id': camera['id'], 'since': '2026-10-01T08:00:00+08:00',
              'as_of': '2026-10-01T08:10:00+08:00', 'limit': 2}
    first = query(devices, 'due_captures', params)
    assert first['execution_status'] == 'planning_only'
    pages = first['items'][:]
    next_offset = first['next_offset']
    while next_offset is not None:
        page = query(devices, 'due_captures', dict(params, offset=next_offset))
        pages.extend(page['items'])
        next_offset = page['next_offset']
    assert [x['slot_at'][14:16] for x in pages] == ['00', '01', '02', '03', '05']
    assert len({x['slot_id'] for x in pages}) == 5
    selected = pages[2]
    assert selected['priority'] == 'focus'
    assert set(selected['focus_labels']) == {'投饵前后', '人工关注'}
    body = {'device_id': camera['id'], 'source_record_id': selected['slot_id'],
            'record_type': 'camera_snapshot', 'captured_at': '2026-10-01T00:02:30Z',
            'evidence_ids': [ev], 'data': {}, 'policy_id': plan['id'], 'slot_at': selected['slot_at']}
    receipt = mutate(devices, 'ingest_device_record', body)
    assert receipt['slot_id'] == selected['slot_id']
    assert receipt['observation_ids'] == []
    remaining = query(devices, 'due_captures', dict(params, limit=100))
    assert len(remaining['items']) == 4
    assert selected['slot_id'] not in {x['slot_id'] for x in remaining['items']}
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'ingest_device_record', dict(body, source_record_id='another-source-id'))
    assert caught.value.code == 'slot_already_received'
    mutate(devices, 'set_capture_policy_status', {'policy_id': plan['id'], 'enabled': False})
    assert query(devices, 'due_captures', params)['items'] == []
    assert mutate(devices, 'ingest_device_record', body)['id'] == receipt['id']
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'ingest_device_record', dict(body, source_record_id='disabled-new-slot',
               slot_at=pages[1]['slot_at']))
    assert caught.value.code == 'policy_disabled'


def test_manual_focus_record_preserves_evidence_withdrawal_without_inference(devices):
    camera, ev = register(devices), evidence(devices, 'image')
    created = mutate(devices, 'ingest_device_record', {
        'device_id': camera['id'], 'source_record_id': 'manual-focus-1', 'record_type': 'manual_note',
        'captured_at': START, 'evidence_ids': [ev], 'data': {}, 'priority': 'focus', 'note': '人工复核摄像画面，原因尚未确认'})
    assert created['observation_ids'] == []
    assert created['epistemic_status'] == 'reported'
    mutate(devices, 'withdraw_evidence', {'evidence_id': ev, 'reason': '合成测试撤回'})
    result = query(devices, 'device_records', {'id': created['id']})['items'][0]
    assert result['evidence_status'] == 'withdrawn'
    assert result['usable_for_inference'] is False
    assert result['note'] == created['note']
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'ingest_device_record', {'device_id': camera['id'], 'source_record_id': 'new-record',
               'record_type': 'camera_snapshot', 'captured_at': START, 'data': {}, 'evidence_ids': [ev]})
    assert caught.value.code == 'evidence_withdrawn'


def test_camera_requires_original_media_kind_and_schema_is_explicit(devices):
    camera, document = register(devices), evidence(devices, 'document')
    body = {'device_id': camera['id'], 'source_record_id': 'bad-image', 'record_type': 'camera_snapshot',
            'captured_at': START, 'evidence_ids': [document], 'data': {}}
    with pytest.raises(DomainError) as caught:
        mutate(devices, 'ingest_device_record', body)
    assert caught.value.code == 'media_evidence_required'
    for schema in DEVICE_SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(DEVICE_SCHEMAS['ingest_device_record'], format_checker=FormatChecker())
    validator.validate(body)
    invalid = dict(body, record_type='gate_status', data={'state': 'partial', 'position_pct': '25.50'})
    validator.validate(invalid)
    assert list(validator.iter_errors(dict(invalid, data={'state': 'open', 'control_command': 'open'})))


def test_device_pagination_and_query_budgets_are_strict(devices):
    bound = field(devices)
    created = {register(devices, bound=bound)['id'] for _ in range(5)}
    seen, offset = [], 0
    while offset is not None:
        result = query(devices, 'devices', {'limit': 2, 'offset': offset})
        seen.extend(x['id'] for x in result['items'])
        offset = result['next_offset']
    assert set(seen) == created and len(seen) == 5
    for params in ({'offset': -1}, {'offset': True}, {'limit': 501}, {'limit': '1.5'}, {'known_at': START}):
        with pytest.raises(DomainError) as caught:
            query(devices, 'devices', params)
        assert caught.value.status == 422
    with pytest.raises(DomainError) as caught:
        query(devices, 'due_captures', {'since': START, 'as_of': '2026-10-10T00:00:00Z'})
    assert caught.value.code == 'invalid_planning_range'


def test_policy_is_immutable_and_invalid_windows_do_not_write(devices):
    camera = register(devices)
    before = count(devices, 'capture_policies')
    with pytest.raises(DomainError):
        policy(devices, camera, focus_windows=[{'start_at': '2026-09-30T00:00:00Z',
               'end_at': '2026-10-01T00:03:00Z', 'interval_seconds': 60, 'label': '范围错误'}])
    with pytest.raises(DomainError):
        policy(devices, camera, interval_seconds=30)
    assert count(devices, 'capture_policies') == before
    plan = policy(devices, camera)
    with pytest.raises(DomainError):
        mutate(devices, 'set_capture_policy_status', {'policy_id': plan['id'], 'enabled': False, 'interval_seconds': 60})
    assert query(devices, 'capture_policies', {'id': plan['id']})['items'][0]['enabled'] is True


@pytest.fixture
def device_api(devices, tmp_path):
    from agri.app import create_app
    assets = tmp_path / 'assets'
    app = create_app({'TESTING': True, 'SERVICE': devices, 'DEMO_MODE': False,
                      'AUTH_TOKENS': {'synthetic-token': ACTOR,
                          'other-tenant-token': {**ACTOR, 'tenant_id': 'device-test-b'}},
                      'ASSET_ROOT': assets, 'SECRET_KEY': 'synthetic-test-session-key'})
    return app.test_client(), assets


def upload(client, data=None, key='synthetic-image-upload'):
    from io import BytesIO
    if data is None:
        from PIL import Image
        buffer = BytesIO()
        Image.new('RGB', (16, 16), 'green').save(buffer, format='PNG')
        data = buffer.getvalue()
    response = client.post('/api/v1/ingestion/assets',
        headers={'Authorization': 'Bearer synthetic-token', 'Idempotency-Key': key},
        data={'source_kind': 'image', 'source_id': 'synthetic-http',
              'file': (BytesIO(data), 'synthetic-frame.png', 'image/png')})
    assert response.status_code == 200, response.get_json()
    return response.get_json()['data']


def post_camera(client, camera, ev, key='api-camera-record'):
    return client.post('/api/v1/device-records',
        headers={'Authorization': 'Bearer synthetic-token', 'Idempotency-Key': key},
        json={'device_id': camera['id'], 'source_record_id': key, 'record_type': 'camera_snapshot',
              'captured_at': START, 'data': {}, 'evidence_ids': [ev['id']]})


def test_device_http_graph_keeps_device_object_and_original_evidence_connected(devices, device_api):
    client, _ = device_api
    camera = register(devices)
    ev = upload(client)
    response = post_camera(client, camera, ev)
    assert response.status_code == 200, response.get_json()
    record = response.get_json()['data']
    graph = client.get('/api/v1/ontology/graph',
        headers={'Authorization': 'Bearer synthetic-token'},
        query_string={'center': camera['bound_entity_key'], 'depth': 3}).get_json()['data']
    ids = {x['id'] for x in graph['nodes']}
    assert {camera['bound_entity_key'], camera['device_entity_key'],
            'device_record:' + record['id'], 'evidence:' + ev['id']} <= ids
    assert any(x['predicate'] == 'registered_at_object' for x in graph['edges'])
    assert any(x['predicate'] == 'source_record_for' and x['target'] == 'device_record:' + record['id'] for x in graph['edges'])
    foreign = client.get('/api/v1/ontology/graph',
        headers={'Authorization': 'Bearer other-tenant-token'},
        query_string={'center': camera['bound_entity_key']})
    assert foreign.status_code == 404
    assert client.get('/api/v1/evidence/' + ev['id'] + '/asset',
        headers={'Authorization': 'Bearer other-tenant-token'}).status_code == 404


def test_camera_record_original_is_retrievable_in_bound_object_inference_bundle(devices, device_api):
    client, _ = device_api
    camera = register(devices)
    ev = upload(client)
    response = post_camera(client, camera, ev)
    assert response.status_code == 200, response.get_json()
    record = response.get_json()['data']
    for entity_key in (camera['bound_entity_key'], camera['device_entity_key']):
        bundle_response = client.get('/api/v1/inference/bundles/' + entity_key,
                                     headers={'Authorization': 'Bearer synthetic-token'})
        assert bundle_response.status_code == 200
        bundle = bundle_response.get_json()['data']
        assert record['id'] in {x['id'] for x in bundle.get('device_records', [])}
        assert ev['id'] in {x['id'] for x in bundle['evidence']}
        assert not bundle['adopted_assertions']
        assert not bundle['observations']  # a frame is not a farm observation by itself


def test_corrupt_original_or_failed_media_decode_cannot_be_marked_inference_usable(devices, device_api):
    client, assets = device_api
    camera = register(devices)
    ev = upload(client)
    response = post_camera(client, camera, ev)
    assert response.status_code == 200, response.get_json()
    record = response.get_json()['data']
    import hashlib
    raw_path = assets / hashlib.sha256(TENANT.encode()).hexdigest() / ev['content_hash']
    raw_path.write_bytes(b'synthetic corruption after receipt')
    assert client.get('/api/v1/evidence/' + ev['id'] + '/asset',
        headers={'Authorization': 'Bearer synthetic-token'}).status_code == 409
    status = client.get('/api/v1/device-records', query_string={'id': record['id']},
        headers={'Authorization': 'Bearer synthetic-token'}).get_json()['data']['items'][0]
    assert status['usable_for_inference'] is False
    invalid = upload(client, b'this is not a decodable image', key='invalid-image-upload')
    assert invalid['metadata']['processing']['status'] == 'failed'
    rejected_or_unusable = post_camera(client, camera, invalid, key='invalid-camera-record')
    assert rejected_or_unusable.status_code in (200, 422)
    if rejected_or_unusable.status_code == 200:
        assert rejected_or_unusable.get_json()['data']['usable_for_inference'] is False
