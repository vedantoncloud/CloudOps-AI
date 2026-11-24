import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal, load_token_registry
from autonomy.control_plane_api import router as control_plane_router


TOKENS = {
    "reader-a": Principal("alice", "reader", "account-a"),
    "operator-a": Principal("bob", "operator", "account-a"),
    "admin-a": Principal("dana", "admin", "account-a"),
    "reader-b": Principal("carol", "reader", "account-b"),
}


def build_client(mode="token", tokens=None):
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode=mode, tokens=TOKENS if tokens is None else tokens)
    app.include_router(control_plane_router)

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


@pytest.mark.parametrize(
    "headers",
    [
        [("Authorization", "Bearer reader-a"), ("Authorization", "Bearer admin-a")],
        [("Authorization", "Bearer reader-a"), ("Authorization", "Bearer unknown")],
        [("Authorization", "Bearer  reader-a")],
        [("Authorization", "Bearer reader-a ")],
        [("Authorization", "Bearer")],
    ],
)
def test_ambiguous_or_malformed_authorization_headers_are_rejected(headers):
    response = build_client().get("/resources", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"

@pytest.mark.parametrize("control", ["\t", "\r", "\n"])
def test_bearer_tokens_reject_ascii_control_whitespace(control):
    response = build_client().get(
        "/resources",
        headers={"Authorization": f"Bearer reader-a{control}"},
    )

    assert response.status_code == 401


def test_valid_bearer_token_containing_letter_t_is_accepted():
    client = build_client(tokens={"valid-token": Principal("alice", "reader", "account-a")})

    response = client.get("/resources", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 200
    assert response.json() == {"subject": "alice", "tenant_id": "account-a"}


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
        "/autonomy/audit/chain/export",
        "/autonomy/audit/database/backup",
        "/autonomy/audit/database/backup/audit",
        "/autonomy/control-plane/summary",
        "/cloud/aws/account-costs",
        "/operations/failures",
        "/operations/aws-failures",
        "/operations/database-failures",
        "/metrics",
    ],
)
def test_operational_audit_diagnostics_require_admin(path):
    client = build_client()

    assert client.get(path, headers={"Authorization": "Bearer reader-a"}).status_code == 403
    assert client.get(path, headers={"Authorization": "Bearer operator-a"}).status_code == 403


def test_platform_admin_can_access_shared_audit_diagnostics():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={**TOKENS, "platform": Principal("platform-ops", "platform_admin", "ops-tenant")})

    @app.get("/autonomy/audit/health")
    def audit_health():
        return {"ok": True}

    response = TestClient(app).get(
        "/autonomy/audit/health",
        headers={"Authorization": "Bearer platform"},
    )

    assert response.status_code == 200


def test_tenant_admin_cannot_access_shared_audit_diagnostics():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens=TOKENS)

    @app.get("/autonomy/audit/health")
    def audit_health():
        return {"ok": True}

    response = TestClient(app).get(
        "/autonomy/audit/health",
        headers={"Authorization": "Bearer admin-a"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform administrator role required"


def test_platform_admin_keeps_explicit_tenant_context():
    tokens = {"platform": Principal("platform-ops", "platform_admin", "ops-tenant")}
    response = build_client(tokens=tokens).get(
        "/resources", headers={"Authorization": "Bearer platform"}
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "platform-ops", "tenant_id": "ops-tenant"}


def test_process_metrics_require_admin():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens=TOKENS)

    @app.get("/metrics")
    def metrics():
        return {"requests": 1}

    client = TestClient(app)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer reader-a"}).status_code == 403
    assert client.get("/metrics", headers={"Authorization": "Bearer operator-a"}).status_code == 403
    assert client.get("/metrics/", headers={"Authorization": "Bearer reader-a"}).status_code == 403
    response = client.get("/metrics", headers={"Authorization": "Bearer admin-a"})
    assert response.status_code == 200
    assert response.json() == {"requests": 1}


@pytest.mark.parametrize(
    "path",
    [
        "/operations/failures/",
    ],
)
def test_admin_only_route_policy_covers_slash_variants_and_subroutes(path):
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens=TOKENS)

    @app.get("/operations/failures/")
    def diagnostic():
        return {"ok": True}

    client = TestClient(app)
    assert client.get(path, headers={"Authorization": "Bearer operator-a"}).status_code == 403
    assert client.get(path, headers={"Authorization": "Bearer admin-a"}).status_code == 200


def test_platform_admin_route_policy_covers_slash_variants_and_subroutes():
    app = FastAPI()
    tokens = {**TOKENS, "platform": Principal("platform-ops", "platform_admin", "ops-tenant")}
    app.add_middleware(AccessControlMiddleware, mode="token", tokens=tokens)

    @app.get("/autonomy/audit/health/")
    @app.get("/autonomy/audit/health/details")
    def diagnostic():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/autonomy/audit/health/", headers={"Authorization": "Bearer admin-a"}).status_code == 403
    assert client.get("/autonomy/audit/health/details", headers={"Authorization": "Bearer admin-a"}).status_code == 403
    assert client.get("/autonomy/audit/health/", headers={"Authorization": "Bearer platform"}).status_code == 200
    assert client.get("/autonomy/audit/health/details", headers={"Authorization": "Bearer platform"}).status_code == 200


def test_admin_can_access_shared_control_plane_summary():
    response = build_client().get(
        "/autonomy/control-plane/summary",
        headers={"Authorization": "Bearer admin-a"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "operational"


def test_health_is_public_and_development_mode_sets_explicit_local_principal():
    client = build_client(mode="development", tokens={})

    assert client.get("/health").status_code == 200
    response = client.get("/resources")
    assert response.json() == {"subject": "local-development", "tenant_id": "local"}


def test_token_registry_requires_complete_valid_claims():
    assert load_token_registry('{"secret":{"subject":"alice","role":"reader","tenant_id":"account-a"}}')["secret"] == TOKENS["reader-a"]
    assert load_token_registry('{"platform":{"subject":"ops","role":"platform_admin","tenant_id":"ops-tenant"}}')["platform"].role == "platform_admin"

    with pytest.raises(RuntimeError, match="subject, role, and tenant_id"):
        load_token_registry('{"secret":{"subject":"alice","role":"reader"}}')


def test_token_registry_parses_optional_expiration_timestamp():
    principal = load_token_registry(
        '{"secret":{"subject":"alice","role":"reader","tenant_id":"account-a","exp":4102444800}}'
    )["secret"]

    assert principal.expires_at == 4102444800.0


@pytest.mark.parametrize("expires_at", [True, False, 0, -1, "4102444800", [], {}, float("nan"), float("inf"), 10**400])
def test_token_registry_rejects_invalid_expiration_timestamps(expires_at):
    import json

    raw = json.dumps({
        "secret": {
            "subject": "alice",
            "role": "reader",
            "tenant_id": "account-a",
            "exp": expires_at,
        }
    })

    with pytest.raises(RuntimeError, match="API token exp must be a finite positive Unix timestamp"):
        load_token_registry(raw)


def test_expired_bearer_token_is_rejected_at_request_time():
    import time

    tokens = {
        "expired": Principal("alice", "reader", "account-a", time.time() - 1),
    }

    response = build_client(tokens=tokens).get(
        "/resources",
        headers={"Authorization": "Bearer expired"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_unexpired_bearer_token_remains_accepted():
    import time

    tokens = {
        "valid": Principal("alice", "reader", "account-a", time.time() + 60),
    }

    response = build_client(tokens=tokens).get(
        "/resources",
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "alice", "tenant_id": "account-a"}


@pytest.mark.parametrize("token", ["bad token", "bad\ttoken", "bad\ntoken"])
def test_token_registry_rejects_credentials_that_cannot_be_sent_as_bearer_tokens(token):
    import json
    raw = json.dumps({token: {"subject": "alice", "role": "reader", "tenant_id": "account-a"}})

    with pytest.raises(RuntimeError, match="contain no whitespace"):
        load_token_registry(raw)

@pytest.mark.parametrize("raw", [
    "{\"secret\":{\"subject\":\"alice\",\"role\":\"reader\",\"tenant_id\":\"account-a\"},\"secret\":{\"subject\":\"mallory\",\"role\":\"admin\",\"tenant_id\":\"account-b\"}}",
    "{\"secret\":{\"subject\":\"alice\",\"subject\":\"mallory\",\"role\":\"reader\",\"tenant_id\":\"account-a\"}}",
])
def test_token_registry_rejects_duplicate_json_keys(raw):
    with pytest.raises(RuntimeError, match="CLOUDOPS_API_TOKENS must be a JSON object"):
        load_token_registry(raw)


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


@pytest.mark.parametrize("mode", [None, "development"])
def test_staging_rejects_permissive_development_authentication(mode):
    with pytest.raises(RuntimeError, match="CLOUDOPS_AUTH_MODE=token is required"):
        AccessControlMiddleware(
            lambda scope, receive, send: None,
            mode=mode,
            tokens={},
            environment="staging",
        )


def test_staging_token_mode_accepts_configured_credentials():
    middleware = AccessControlMiddleware(
        lambda scope, receive, send: None,
        mode="token",
        tokens=TOKENS,
        environment="staging",
    )

    assert middleware.mode == "token"
    assert middleware.environment == "staging"
