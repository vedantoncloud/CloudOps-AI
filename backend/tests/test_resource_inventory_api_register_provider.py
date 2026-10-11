from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import (
    provider_registry,
    register_provider,
    router,
)


class RegistrationTestProvider:
    provider_name = "aws"

    def get_ec2_instances(self, state=None, tag_filter=None):
        return {
            "instances": [
                {
                    "instance_id": "i-register-001",
                    "state": "running",
                    "instance_type": "t3.small",
                    "region": "ap-south-1",
                }
            ]
        }

    def get_s3_buckets(self):
        return {"buckets": []}


def test_register_provider_registers_provider_for_inventory_api():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    provider = RegistrationTestProvider()

    try:
        result = register_provider(provider)

        assert result is None
        assert provider_registry.has("aws") is True
        assert provider_registry.get("aws") is provider

        app = FastAPI()
        app.include_router(router)

        response = TestClient(app).get(
            "/autonomy/resources?provider=aws&resource_type=ec2"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["provider"] == "aws"
        assert body["resource_type"] == "ec2"
        assert body["read_only"] is True
        assert body["count"] == 1

        assert body["resources"] == [
            {
                "provider": "aws",
                "resource_type": "ec2",
                "resource_id": "i-register-001",
                "attributes": {
                    "instance_id": "i-register-001",
                    "state": "running",
                    "instance_type": "t3.small",
                    "region": "ap-south-1",
                },
                "read_only": True,
            }
        ]

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")


def test_register_provider_rejects_duplicate_provider():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    try:
        register_provider(RegistrationTestProvider())

        import pytest

        with pytest.raises(
            ValueError,
            match="provider already registered",
        ):
            register_provider(RegistrationTestProvider())

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")