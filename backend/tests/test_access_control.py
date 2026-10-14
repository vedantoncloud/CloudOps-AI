import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal, load_token_registry


TOKENS = {
    "reader-a": Principal("alice", "reader", "account-a"),
    "operator-a": Principal("bob", "operator", "account-a"),
    "admin-a": Principal("dana", "admin", "account-a"),
    "reader-b": Principal("carol", "reader", "account-b"),
}


def build_client(mode="token", tokens=None):
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode=mode, tokens=TOKENS if tokens is None else tokens)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get("/resources")
    def read_resource(request: Request):
        principal = request.state.principal
        return {"subject": principal.subject, "tenant_id": request.state.tenant_id}

    @app.post("/approvals")
    def approve():
        return {"approved": True}

    return TestClient(app)


def test_protected_routes_reject_missing_and_invalid_bearer_tokens():
    client = build_client()

    assert client.get("/resources").status_code == 401
    response = client.get("/resources", headers={"Authorization": "Bearer unknown"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_authenticated_principal_and_tenant_are_attached_to_request():
    response = build_client().get(
        "/resources",
        headers={"Authorization": "Bearer reader-a", "X-Cloud-Tenant": "account-a"},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "alice", "tenant_id": "account-a"}


def test_tenant_header_cannot_select_another_tenant():
    response = build_client().get(
        "/resources",
        headers={"Authorization": "Bearer reader-a", "X-Cloud-Tenant": "account-b"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant access denied"


def test_reader_cannot_perform_approval_operation():
    response = build_client().post("/approvals", headers={"Authorization": "Bearer reader-a"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/autonomy/audit/health",
        "/autonomy/audit/pending",
        "/autonomy/audit/reconciliation",
        "/autonomy/audit/integrity",
    ],
)
def test_operational_audit_diagnostics_require_admin(path):
    client = build_client()

    assert client.get(path, headers={"Authorization": "Bearer reader-a"}).status_code == 403
    assert client.get(path, headers={"Authorization": "Bearer operator-a"}).status_code == 403


def test_admin_can_access_operational_audit_diagnostics():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens=TOKENS)

    @app.get("/autonomy/audit/health")
    def audit_health():
        return {"ok": True}

    response = TestClient(app).get(
        "/autonomy/audit/health",
        headers={"Authorization": "Bearer admin-a"},
    )

    assert response.status_code == 200


def test_health_is_public_and_development_mode_sets_explicit_local_principal():
    client = build_client(mode="development", tokens={})

    assert client.get("/health").status_code == 200
    response = client.get("/resources")
    assert response.json() == {"subject": "local-development", "tenant_id": "local"}


def test_token_registry_requires_complete_valid_claims():
    assert load_token_registry('{"secret":{"subject":"alice","role":"reader","tenant_id":"account-a"}}')["secret"] == TOKENS["reader-a"]

    with pytest.raises(RuntimeError, match="subject, role, and tenant_id"):
        load_token_registry('{"secret":{"subject":"alice","role":"reader"}}')


def test_token_mode_fails_closed_without_credentials():
    with pytest.raises(RuntimeError, match="CLOUDOPS_API_TOKENS is required"):
        AccessControlMiddleware(lambda scope, receive, send: None, mode="token", tokens={})


def test_production_rejects_permissive_development_authentication():
    with pytest.raises(RuntimeError, match="CLOUDOPS_AUTH_MODE=token is required"):
        AccessControlMiddleware(
            lambda scope, receive, send: None,
            mode="development",
            tokens={},
            environment="production",
        )


def test_production_token_mode_requires_configured_credentials():
    with pytest.raises(RuntimeError, match="CLOUDOPS_API_TOKENS is required"):
        AccessControlMiddleware(
            lambda scope, receive, send: None,
            mode="token",
            tokens={},
            environment="production",
        )
