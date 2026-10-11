"""HTTP boundary tests use a service double; they do not certify a database backend."""
from copy import deepcopy
import pytest


class ServiceSpy:
    def __init__(self):
        self.calls = []
        self.failure = None

    def mutate(self, action, tenant, actor, payload, key):
        self.calls.append(("mutate", action, tenant, deepcopy(actor), deepcopy(payload), key))
        if self.failure:
            raise self.failure
        return {"id": "test-record", "synthetic": True}

    def query(self, action, tenant, actor, params):
        self.calls.append(("query", action, tenant, deepcopy(actor), dict(params)))
        if self.failure:
            raise self.failure
        return {"items": [], "synthetic": True}

    def public_trace(self, code):
        self.calls.append(("public_trace", code))
        if self.failure:
            raise self.failure
        return {"code": code, "product_name": "合成产品", "current_status": {"state": "published"}}


@pytest.fixture()
def api():
    from agri.app import create_app
    spy = ServiceSpy()
    app = create_app({
        "TESTING": True,
        "SERVICE": spy,
        "DEMO_MODE": False,
        "AUTH_TOKENS": {
            "test-admin": {"id": "alice", "tenant_id": "tenant-a", "roles": ["admin"]},
            "test-viewer": {"id": "bob", "tenant_id": "tenant-a", "roles": ["viewer"]},
            "test-other": {"id": "carol", "tenant_id": "tenant-b", "roles": ["admin"]},
        },
    })
    return app.test_client(), spy


def auth(token="test-admin", **extra):
    return {"Authorization": "Bearer " + token, **extra}


def test_private_request_requires_valid_bearer(api):
    client, spy = api
    for headers in ({}, auth("unknown"), {"Authorization": "Basic test-admin"}):
        response = client.get("/api/v1/ontology/entities", headers=headers)
        assert response.status_code == 401
        assert response.json["error"]["code"]
    assert spy.calls == []


def test_tenant_header_cannot_override_configured_identity(api):
    client, spy = api
    response = client.get("/api/v1/ontology/entities", headers=auth(**{"X-Tenant-ID": "tenant-b"}))
    assert response.status_code == 200
    assert spy.calls[-1][2] == "tenant-a"
    assert spy.calls[-1][3]["id"] == "alice"


def test_each_token_selects_its_own_tenant(api):
    client, spy = api
    response = client.get("/api/v1/ontology/entities", headers=auth("test-other"))
    assert response.status_code == 200
    assert spy.calls[-1][2] == "tenant-b"


def test_actor_roles_are_forwarded_to_authorizing_service(api):
    client, spy = api
    response = client.get("/api/v1/ontology/entities", headers=auth("test-viewer"))
    assert response.status_code == 200
    assert spy.calls[-1][3]["roles"] == ["viewer"]


def test_mutation_requires_idempotency_key(api):
    client, spy = api
    response = client.post("/api/v1/ontology/entities", json={"entity_type": "field", "name": "合成对象"}, headers=auth())
    assert response.status_code == 422
    assert spy.calls == []


def test_mutation_dispatch_preserves_actor_key_and_tenant_boundary(api):
    client, spy = api
    response = client.post("/api/v1/ontology/entities", json={"entity_type": "field", "name": "合成对象"},
                           headers=auth(**{"Idempotency-Key": "create-1", "X-Tenant-ID": "tenant-b"}))
    assert response.status_code in (200, 201)
    call = spy.calls[-1]
    assert call[0] == "mutate"
    assert call[2] == "tenant-a"
    assert call[3]["id"] == "alice"
    assert call[-1] == "create-1"


def test_domain_error_keeps_http_status_and_structured_details(api):
    from agri.service import DomainError
    client, spy = api
    spy.failure = DomainError(409, "idempotency_conflict", "Key already used", {"field": "idempotency_key"})
    response = client.post("/api/v1/ontology/entities", json={"entity_type": "field", "name": "合成对象"},
                           headers=auth(**{"Idempotency-Key": "create-1"}))
    assert response.status_code == 409
    assert response.json["error"]["code"] == "idempotency_conflict"
    assert response.json["error"]["details"] == {"field": "idempotency_key"}


def test_public_route_is_separate_from_authenticated_query(api):
    client, spy = api
    response = client.get("/api/v1/public/trace/opaque-test-code")
    assert response.status_code == 200
    assert spy.calls == [("public_trace", "opaque-test-code")]


def test_withdrawn_public_response_is_not_cached_as_published(api):
    from agri.service import DomainError
    client, spy = api
    spy.failure = DomainError(410, "publication_withdrawn", "Publication withdrawn", {})
    response = client.get("/api/v1/public/trace/opaque-test-code")
    assert response.status_code == 410
    assert response.json["error"]["code"] == "publication_withdrawn"
    assert "no-store" in response.headers.get("Cache-Control", "")


def test_demo_session_disabled_in_normal_configuration(api):
    client, spy = api
    response = client.post("/api/v1/auth/demo", json={})
    assert response.status_code in (403, 404)
    assert spy.calls == []


def test_invalid_json_object_never_reaches_service(api):
    client, spy = api
    for body in ([], "text", 5):
        response = client.post("/api/v1/ontology/entities", json=body,
                               headers=auth(**{"Idempotency-Key": "invalid-body"}))
        assert response.status_code == 422
    assert spy.calls == []


def test_cross_origin_mutation_is_rejected_before_service(api):
    client, spy = api
    response = client.post("/api/v1/ontology/entities", json={"name": "合成"},
                           headers=auth(**{"Idempotency-Key": "cross-origin", "Origin": "https://external.invalid"}))
    assert response.status_code == 403
    assert spy.calls == []


def test_openapi_declares_authenticated_write_and_public_read(api):
    client, _ = api
    spec = client.get("/api/v1/openapi.json").json
    write = spec["paths"]["/api/v1/ontology/entities"]["post"]
    assert write["security"] == [{"bearerAuth": []}]
    assert any(p["name"] == "Idempotency-Key" and p["required"] for p in write["parameters"])
    assert spec["paths"]["/api/v1/public/trace/{code}"]["get"]["security"] == []


def test_body_cannot_smuggle_tenant_identity(api):
    client, spy = api
    response = client.post("/api/v1/ontology/entities", json={"entity_type": "field", "name": "合成", "tenant_id": "tenant-b"},
                           headers=auth(**{"Idempotency-Key": "tenant-smuggle"}))
    assert response.status_code == 422
    assert spy.calls == []


def test_decimal_quantity_must_not_arrive_as_json_float(api):
    client, spy = api
    response = client.post("/api/v1/trace/events", json={
        "event_type": "split", "occurred_at": "2026-10-11T00:00:00Z", "evidence_ids": [],
        "inputs": [{"lot_key": "7e1a21ba-7856-4a0d-8a6c-506c3f97c93a", "quantity": 0.1, "unit": "kg"}],
    }, headers=auth(**{"Idempotency-Key": "float-rejected"}))
    assert response.status_code == 422
    assert spy.calls == []
