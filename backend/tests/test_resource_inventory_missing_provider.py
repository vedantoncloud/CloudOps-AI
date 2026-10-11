from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import (
    provider_registry,
    router,
)


def test_inventory_returns_400_when_provider_is_not_registered():
    provider_name = "unregistered-test-provider"

    if provider_registry.has(provider_name):
        provider_registry.unregister(provider_name)

    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get(
        "/autonomy/resources",
        params={
            "provider": provider_name,
            "resource_type": "ec2",
        },
    )

    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]
