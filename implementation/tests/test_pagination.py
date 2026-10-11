"""Resource paging and committed-event cursors are deliberately separate.

The shared fixture exercises SQLite locally and skips PostgreSQL explicitly
unless a dedicated TEST_DATABASE_URL is configured.
"""
import pytest

from agri.service import DomainError


TENANT = 'paging-test'
ACTOR = {'id': 'synthetic-pagination-admin', 'tenant_id': TENANT, 'roles': ['admin']}


def test_resource_pages_cover_unique_records_and_idempotent_replay(service):
    expected = []
    for number in range(5):
        payload = {'entity_type': 'field', 'name': 'Synthetic field ' + str(number)}
        record = service.mutate('create_entity', TENANT, ACTOR, payload, 'field-' + str(number))
        expected.append(record['entity_key'])
        replay = service.mutate('create_entity', TENANT, ACTOR, payload, 'field-' + str(number))
        assert replay == record

    # Reading the same page is stable when the filtered collection is unchanged.
    first = service.query('entities', TENANT, ACTOR, {'limit': 2, 'offset': 0})
    assert first == service.query('entities', TENANT, ACTOR, {'limit': 2, 'offset': '0'})
    assert first['has_more'] and first['next_offset'] == 2
    keys = [record['entity_key'] for record in first['items']]
    offset = first['next_offset']
    page_count = 1
    while offset is not None:
        page = service.query('entities', TENANT, ACTOR, {'limit': 2, 'offset': offset})
        keys.extend(record['entity_key'] for record in page['items'])
        offset = page['next_offset']
        page_count += 1
        assert page_count <= 3
    assert len(keys) == len(set(keys)) == 5
    assert set(keys) == set(expected)
    assert page_count == 3
    exhausted = service.query('entities', TENANT, ACTOR, {'limit': 2, 'offset': 100})
    assert exhausted['items'] == [] and exhausted['next_offset'] is None

    # Idempotent replay must not add a change event that shifts subsequent pages.
    changes = service.query('changes', TENANT, ACTOR, {'limit': 2})
    sequences = [item['sequence'] for item in changes['items']]
    while changes['has_more']:
        changes = service.query('changes', TENANT, ACTOR, {'limit': 2, 'cursor': changes['next_cursor']})
        assert 'next_offset' not in changes
        sequences.extend(item['sequence'] for item in changes['items'])
    assert sequences == list(range(1, 6))


def test_offsets_are_strict_and_cannot_skip_committed_change_events(service):
    for invalid in (-1, '-1', 1.5, True, None, '1.0', '', ' 1', 'abc', 9223372036854775808):
        with pytest.raises(DomainError) as caught:
            service.query('entities', TENANT, ACTOR, {'offset': invalid})
        assert caught.value.status == 422
        assert caught.value.code == 'invalid_offset'
    # Even zero is disallowed on this endpoint: clients must use next_cursor.
    for offset in (0, '0', 3, -1):
        with pytest.raises(DomainError) as caught:
            service.query('changes', TENANT, ACTOR, {'offset': offset})
        assert caught.value.status == 422
        assert caught.value.code == 'cursor_only'
