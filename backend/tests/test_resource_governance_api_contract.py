
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_governance_api import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_governance_api_returns_explicit_provider_adapter_boundary():
    client = TestClient(make_app())

    response = client.get(
        "/autonomy/resources/ec2/i-contract-123/governance"
    )

    assert response.status_code == 501

    body = response.json()

    assert set(body) == {"detail"}
    assert body["detail"] == (
        "Resource governance API requires an application provider "
        "adapter and does not perform provider mutations."
    )
