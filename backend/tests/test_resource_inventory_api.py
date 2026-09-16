from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import (
    discovery,
    provider_registry,
    router,
)


class FakeProvider:
    provider_name = "aws"

    def get_ec2_instances(self):
        return {
            "resources": [
                {
                    "instance_id": "i-001",
                    "state": "running",
                    "tags": {"Environment": "prod"},
                },
                {
                    "instance_id": "i-002",
                    "state": "stopped",
                },
            ]
        }

    def get_s3_buckets(self):
        return {
            "buckets": [
                {"name": "logs-prod"},
            ]
        }


def make_client():
    # ProviderRegistry intentionally has no clear() API.
    # Replace the module-level registry instance contents through
    # its supported unregister operation when a provider is present.
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")
    provider_registry.register(FakeProvider())

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_inventory_returns_ec2_resources():
    response = make_client().get(
        "/autonomy/resources?provider=aws&resource_type=ec2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "aws"
    assert body["resource_type"] == "ec2"
    assert body["read_only"] is True
    assert body["count"] == 2
    assert body["resources"][0]["resource_id"] == "i-001"


def test_inventory_returns_s3_resources():
    response = make_client().get(
        "/autonomy/resources?provider=aws&resource_type=s3"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["resources"][0]["resource_id"] == "logs-prod"


def test_inventory_normalizes_query_case():
    response = make_client().get(
        "/autonomy/resources?provider=AWS&resource_type=EC2"
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "aws"
    assert response.json()["resource_type"] == "ec2"


def test_unknown_provider_returns_400():
    response = make_client().get(
        "/autonomy/resources?provider=azure&resource_type=ec2"
    )

    assert response.status_code == 400


def test_unsupported_resource_type_returns_400():
    response = make_client().get(
        "/autonomy/resources?provider=aws&resource_type=lambda"
    )

    assert response.status_code == 400


def test_inventory_response_is_explicitly_read_only():
    response = make_client().get(
        "/autonomy/resources?provider=aws&resource_type=ec2"
    )

    body = response.json()
    assert body["read_only"] is True
    assert all(item["read_only"] is True for item in body["resources"])


def test_inventory_preserves_resource_attributes():
    response = make_client().get(
        "/autonomy/resources?provider=aws&resource_type=ec2"
    )

    resource = response.json()["resources"][0]
    assert resource["attributes"]["state"] == "running"
    assert resource["attributes"]["tags"] == {"Environment": "prod"}


def test_inventory_empty_result_is_valid():
    class EmptyProvider(FakeProvider):
        def get_ec2_instances(self):
            return {"resources": []}

    if provider_registry.has("aws"):
        provider_registry.unregister("aws")
    provider_registry.register(EmptyProvider())

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get(
        "/autonomy/resources?provider=aws&resource_type=ec2"
    )

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["resources"] == []
