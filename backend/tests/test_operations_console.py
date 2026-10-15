from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from main import app, console


def test_console_is_served_to_authenticated_reader():
    client = TestClient(app)
    response = client.get("/console")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "CloudOps AI" in response.text
    assert "Pending approvals" in response.text
    assert "Your autonomous run history" in response.text
    assert "governance" in response.text
    assert "Action plans" in response.text
    assert "Browse objects" in response.text
    assert "Object key prefix" in response.text
    assert "Next page" in response.text


def test_console_uses_tenant_api_contracts_and_does_not_persist_bearer_token():
    response = TestClient(app).get("/console")

    assert "/autonomy/resources/" in response.text
    assert "/autonomy/approvals?limit=50" in response.text
    assert "/autonomy/runs?limit=50" in response.text
    assert "/autonomy/plans?limit=50" in response.text
    assert "/autonomy/ec2/instances/${encodeURIComponent(resource.id)}/plans" in response.text
    assert "/autonomy/s3/buckets/${encodeURIComponent(resource.id)}/plans" in response.text
    assert "Dry run" in response.text
    assert "localStorage" not in response.text
    assert "sessionStorage" not in response.text


def test_console_s3_object_browser_uses_bounded_resumable_listing_contract():
    response = TestClient(app).get("/console")

    assert "max_keys:$('objectPageSize').value" in response.text
    assert "query.set('prefix',prefix)" in response.text
    assert "query.set('continuation_token',token)" in response.text
    assert "data.next_continuation_token" in response.text
    assert "encodeURIComponent(activeBucket)" in response.text


def test_console_is_protected_by_token_authentication():
    secured = FastAPI()
    secured.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"valid": Principal("operator", "operator", "tenant-a")},
    )
    secured.add_api_route("/console", console)
    client = TestClient(secured)

    assert client.get("/console").status_code == 401
    response = client.get("/console", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
