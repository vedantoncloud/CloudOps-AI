from fastapi import FastAPI
from fastapi.testclient import TestClient

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
