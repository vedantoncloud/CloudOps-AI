from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy import resource_governance_api
from autonomy.resource_governance_api import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_governance_api_executes_real_governance_engine():
    client = TestClient(make_app())

    response = client.get(
        "/autonomy/resources/ec2/i-task21-governance/governance"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["resource_id"] == "i-task21-governance"
    assert body["resource_type"] == "ec2"
    assert body["provider"] == "aws"
    assert body["allowed_for_decision"] is True
    assert body["decision"] == "allow"
    assert body["read_only"] is True

    assert body["blocked"] is False
    assert body["requires_human_review"] is False

    assert "evidence" in body
    assert body["evidence"]["decision"] == "allow"
    assert body["evidence"]["allowed"] is True


def test_governance_lookup_hides_resources_owned_by_another_tenant(monkeypatch):
    class TaggedProvider:
        provider_name = "aws"

        def get_resource(self, resource_type, resource_id):
            return {
                "provider": "aws",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "tags": {"CloudOpsTenantId": "account-b"},
            }

    monkeypatch.setattr(
        resource_governance_api.provider_registry,
        "get",
        lambda name: TaggedProvider(),
    )
    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"tenant-a": Principal("alice", "reader", "account-a")},
    )
    app.include_router(router)

    response = TestClient(app).get(
        "/autonomy/resources/ec2/i-private/governance",
        headers={"Authorization": "Bearer tenant-a"},
    )

    assert response.status_code == 404
