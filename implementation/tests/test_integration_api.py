"""HTTP -> source mapping -> isolated database integration, never live farm data."""
import json
import pytest


def bundle():
    return {
        'packages': [{
            'package_id': 'http.mapping', 'version': '1.0.0', 'namespace': 'urn:http:mapping:',
            'types': [{'type_id': 'http:Plot', 'identity_type': 'http:plot', 'label': '合成测试田块'}],
            'properties': [{'property_id': 'http:name', 'label': '名称', 'applies_to': ['http:Plot'],
                            'usage': 'attribute', 'value_type': 'string'}], 'predicates': []}],
        'profile': {'source_id': 'synthetic-http', 'profile_id': 'http-profile', 'version': '1.0.0',
                    'tables': [{'table': 'plots', 'primary_key': ['id'], 'key_types': {'id': 'string'},
                                'type_ref': {'package_id': 'http.mapping', 'version': '1.0.0', 'type_id': 'http:Plot'},
                                'name_field': 'name', 'fields': [{'source_field': 'name', 'property_id': 'http:name'}],
                                'relations': [], 'deferred_fields': [], 'rejected_fields': ['access_token']}]}}


def batch():
    return {'source_id': 'synthetic-http', 'profile_id': 'http-profile', 'version': '1.0.0',
            'batch_id': 'synthetic-001', 'observed_at': '2026-01-01T00:00:00Z',
            'records': [{'table': 'plots', 'values': {'id': 'SYNTHETIC-01', 'name': '测试田块'}}]}


@pytest.fixture()
def client(database):
    from agri.app import create_app
    from agri.source_mapping import SourceMappingService
    app = create_app({'TESTING': True, 'SERVICE': SourceMappingService(database), 'DEMO_MODE': False,
                      'AUTH_TOKENS': {
                          'synthetic-admin': {'id': 'admin-test', 'tenant_id': 'test-a', 'roles': ['admin']},
                          'synthetic-viewer': {'id': 'viewer-test', 'tenant_id': 'test-a', 'roles': ['viewer']},
                          'synthetic-other': {'id': 'other-test', 'tenant_id': 'test-b', 'roles': ['admin']}}})
    return app.test_client()


def headers(key=None, token='synthetic-admin'):
    value = {'Authorization': 'Bearer ' + token}
    if key: value['Idempotency-Key'] = key
    return value


def test_bundle_preview_then_apply_roundtrip(client):
    body = dict(bundle(), batch=batch())
    preview = client.post('/api/v1/integration/bundles/preview', json=body, headers=headers())
    assert preview.status_code == 200, preview.json
    assert client.get('/api/v1/integration/profiles', headers=headers()).json['data']['items'] == []
    assert client.get('/api/v1/integration/bindings', headers=headers()).json['data']['items'] == []
    applied = client.post('/api/v1/integration/bundles', json=body, headers=headers('install'))
    assert applied.status_code == 200, applied.json
    repeated = client.post('/api/v1/integration/bundles', json=body, headers=headers('install'))
    assert repeated.json['data'] == applied.json['data']
    bindings = client.get('/api/v1/integration/bindings?source_id=synthetic-http', headers=headers()).json['data']['items']
    assert len(bindings) == 1
    entity = client.get('/api/v1/ontology/entities/' + bindings[0]['entity_key'], headers=headers()).json['data']
    assert entity['name'] == '测试田块'
    other = client.get('/api/v1/integration/bindings', headers=headers(token='synthetic-other'))
    assert other.json['data']['items'] == []
    events = client.get('/api/v1/trace/changes', headers=headers()).json['data']['items']
    notices = [item['payload'] for item in events if item['event_type'] == 'install_source_bundle']
    assert len(notices) == 1
    assert notices[0]['source_id'] == body['batch']['source_id']
    assert notices[0]['batch_id'] == body['batch']['batch_id']
    assert notices[0]['profile_id'] == body['batch']['profile_id']
    assert 'values' not in str(notices[0])


def test_source_routes_require_auth_write_role_and_idempotency(client):
    assert client.post('/api/v1/integration/bundles', json=bundle()).status_code == 401
    assert client.post('/api/v1/integration/bundles', json=bundle(), headers=headers()).status_code == 422
    assert client.post('/api/v1/integration/bundles', json=bundle(), headers=headers('denied', 'synthetic-viewer')).status_code == 403
    assert client.post('/api/v1/integration/bundles/preview', json=bundle(), headers=headers(token='synthetic-viewer')).status_code == 403


def test_invalid_batch_rolls_back_bundle_and_never_retains_secret(client):
    body = dict(bundle(), batch=batch())
    body['batch']['records'][0]['values']['access_token'] = 'synthetic-forbidden-value'
    response = client.post('/api/v1/integration/bundles', json=body, headers=headers('bad-bundle'))
    assert response.status_code == 422, response.json
    assert 'synthetic-forbidden-value' not in response.get_data(as_text=True)
    assert client.get('/api/v1/ontology/packages', headers=headers()).json['data']['items'] == []
    assert client.get('/api/v1/evidence', headers=headers()).json['data']['items'] == []


def test_contract_documents_new_routes_and_no_client_entity_uuid(client):
    spec = client.get('/api/v1/openapi.json').json
    for path in ('/integration/bundles', '/integration/batches', '/integration/profiles'):
        op = spec['paths']['/api/v1' + path]['post']
        assert op['security'] == [{'bearerAuth': []}]
        assert any(p['name'] == 'Idempotency-Key' and p['required'] for p in op['parameters'])
    body = batch()
    body['records'][0]['entity_key'] = '06b43809-c6e9-49b3-99cf-e7ca7c441288'
    assert client.post('/api/v1/integration/batches', json=body, headers=headers('bad-id')).status_code == 422


def test_oversized_and_cross_origin_batch_are_rejected(client):
    body = batch()
    body['records'][0]['values']['name'] = 'x' * (2 * 1024 * 1024)
    assert client.post('/api/v1/integration/preview', json=body, headers=headers()).status_code == 413
    assert client.post('/api/v1/integration/preview', json=batch(),
                       headers={**headers(), 'Origin': 'https://untrusted.invalid'}).status_code == 403


@pytest.mark.parametrize('invalid_kind',['duplicate_top','duplicate_values','nan','infinity','negative_infinity','overflow'])
@pytest.mark.parametrize('preview',[False,True])
def test_ambiguous_json_rejected_before_database_or_idempotency_mutation(client,invalid_kind,preview):
    body = dict(bundle(),batch=batch())
    raw = json.dumps(body,ensure_ascii=False)
    if invalid_kind == 'duplicate_top':
        raw = '{"batch":' + json.dumps(body['batch'],ensure_ascii=False) + ',' + raw[1:]
    elif invalid_kind == 'duplicate_values':
        raw = raw.replace('"name": "测试田块"','"name": "被覆盖值", "name": "测试田块"')
    else:
        literal = {'nan':'NaN','infinity':'Infinity','negative_infinity':'-Infinity','overflow':'1e10000'}[invalid_kind]
        raw = raw.replace('"name": "测试田块"','"name": ' + literal)
    database = client.application.extensions['agri_service'].db
    tables = ['ontology_packages','ontology_types','source_profiles','entities','source_bindings',
              'source_binding_revisions','source_batches','evidence','evidence_links','idempotency','audit_log','outbox','outbox_counters']
    def counts():
        with database.transaction() as tx:
            return {table:tx.execute('SELECT COUNT(*) AS n FROM '+table).fetchone()['n'] for table in tables}
    before = counts()
    route = '/api/v1/integration/bundles' + ('/preview' if preview else '')
    response = client.post(route,data=raw.encode('utf-8'),content_type='application/json',headers=headers('strict-json-retry'))
    assert response.status_code == 422, response.json
    assert response.json['error']['code'] == 'invalid_request'
    assert counts() == before
    # A rejected raw body cannot reserve the idempotency key. Normal JSON must
    # still pass unchanged through the same endpoint and authentication path.
    accepted = client.post(route,json=body,headers=headers('strict-json-retry'))
    assert accepted.status_code == 200, accepted.json
    if preview:
        assert counts() == before
    else:
        assert counts()['entities'] == 1 and counts()['source_bindings'] == 1
