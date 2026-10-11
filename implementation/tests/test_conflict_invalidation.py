"""A newly adopted disagreement must invalidate previously published content.

Fixtures are synthetic and isolated. The shared PostgreSQL fixture is a separate
explicit test gate, never substituted by the local SQLite result.
"""
import json
from uuid import uuid4


TENANT = 'conflict-invalidation-test'
ACTOR = {'id': 'synthetic-reviewer', 'tenant_id': TENANT, 'roles': ['admin']}


def write(service, action, payload, key=None):
    return service.mutate(action, TENANT, ACTOR, payload, key or uuid4().hex)


def setup_publication(service):
    evidence = write(service, 'create_evidence', {
        'kind': 'synthetic_report', 'uri': 'urn:synthetic:conflict-report',
        'content_hash': 'b' * 64, 'metadata': {'synthetic': True},
    })['id']
    batch = write(service, 'create_entity', {'entity_type': 'production_batch', 'name': 'Synthetic production'})['entity_key']
    lot = write(service, 'create_lot', {'name': 'Synthetic material', 'product_type': 'test:rice', 'unit': 'kg', 'production_batch_key': batch})['lot_key']
    write(service, 'create_event', {
        'event_type': 'harvest', 'occurred_at': '2026-10-11T01:00:00+08:00',
        'evidence_ids': [evidence], 'participants': [{'entity_key': batch, 'role': 'production_origin'}],
        'outputs': [{'lot_key': lot, 'quantity': '10', 'unit': 'kg'}],
    })
    first = claim(service, lot, evidence, '7', 'sample-A')
    write(service, 'review_assertion', {'assertion_id': first, 'status': 'accepted', 'rationale': 'Synthetic initial review'})
    publication = write(service, 'publish', {'lot_key': lot, 'summary': {}, 'assertion_ids': [first], 'evidence_ids': [evidence]})
    return evidence, lot, first, publication


def claim(service, lot, evidence, value, scope):
    return write(service, 'create_assertion', {
        'subject_key': lot, 'predicate_id': 'test:ph', 'evidence_ids': [evidence],
        'value': {'value': value, 'unit': 'pH', 'scope': scope, 'public_text': 'Reviewed synthetic pH ' + value},
    })['id']


def stored_publication(database, publication_id):
    with database.transaction() as tx:
        row = dict(tx.execute('SELECT body,content_hash,status FROM publications WHERE tenant_id=%s AND id=%s', (TENANT, publication_id)).fetchone())
    if isinstance(row['body'], str):
        row['body'] = json.loads(row['body'])
    return row


def test_new_comparable_conflict_invalidates_existing_publication_atomically(service, database):
    evidence, lot, first, publication = setup_publication(service)
    original = stored_publication(database, publication['id'])
    before = service.public_trace(publication['public_code'])
    assert before['status'] == 'published'

    # A different sampling scope must not withdraw the existing statement.
    other_scope = claim(service, lot, evidence, '3', 'sample-B')
    write(service, 'review_assertion', {'assertion_id': other_scope, 'status': 'accepted', 'rationale': 'Different scope'})
    assert service.public_trace(publication['public_code'])['status'] == 'published'

    conflicting = claim(service, lot, evidence, '3', 'sample-A')
    payload = {'assertion_id': conflicting, 'status': 'accepted', 'rationale': 'Conflicting source newly reviewed'}
    reviewed = write(service, 'review_assertion', payload, 'review-conflict-once')
    assert reviewed['invalidated_publications'] == [publication['id']]
    assert write(service, 'review_assertion', payload, 'review-conflict-once') == reviewed
    current = service.public_trace(publication['public_code'])
    assert current['status'] == 'withdrawn'
    assert current['data']['quality_statements'] == []
    assert current['status_revision'] > before['status_revision']

    stored = stored_publication(database, publication['id'])
    assert stored['status'] == 'withdrawn'
    assert stored['body'] == original['body']
    assert stored['content_hash'] == original['content_hash']
    changes = service.query('changes', TENANT, ACTOR, {'limit': 1000})['items']
    notices = [x for x in changes if publication['id'] in x['payload'].get('invalidated_publications', [])]
    assert len(notices) == 1
    assert notices[0]['payload']['invalidation_reason'] == 'assertion_conflict'
    with database.transaction() as tx:
        rows = tx.execute('SELECT details FROM audit_log WHERE tenant_id=%s AND action=%s AND target_id=%s',
                          (TENANT, 'publication.invalidated', publication['id'])).fetchall()
    assert len(rows) == 1


def test_public_read_fails_closed_for_legacy_conflict_without_notification(service, database):
    evidence, lot, first, publication = setup_publication(service)
    original = stored_publication(database, publication['id'])
    second = claim(service, lot, evidence, '3', 'sample-A')
    # Simulates loading a legacy accepted record which missed change propagation.
    # Production callers must use the service, not direct database updates.
    with database.transaction() as tx:
        tx.execute('UPDATE assertions SET status=%s WHERE tenant_id=%s AND id=%s', ('accepted', TENANT, second))
    current = service.public_trace(publication['public_code'])
    assert current['status'] == 'withdrawn'
    assert current['data']['quality_statements'] == []
    assert stored_publication(database, publication['id']) == original
