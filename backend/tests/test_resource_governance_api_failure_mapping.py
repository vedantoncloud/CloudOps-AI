from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_governance_api import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_governance_api_returns_governance_result_for_supported_resource():
    client = TestClient(make_app())

    response = client.get(
        "/autonomy/resources/ec2/i-failure-123/governance"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["provider"] == "aws"
    assert body["resource_type"] == "ec2"
    assert body["resource_id"] == "i-failure-123"
    assert body["decision"] == "allow"
    assert body["allowed_for_decision"] is True
