from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import provider_registry, router


class DefaultParametersProvider:
    provider_name = "aws"

    def get_ec2_instances(self):
        return {
            "instances": [
                {"instance_id": "i-default-001", "state": "running"}
            ]
        }

    def get_s3_buckets(self):
        return {"buckets": []}


def test_inventory_endpoint_uses_default_query_parameters():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    provider_registry.register(DefaultParametersProvider())

    try:
        app = FastAPI()
        app.include_router(router)

        response = TestClient(app).get("/autonomy/resources")

        assert response.status_code == 200

        body = response.json()

        assert body["provider"] == "aws"
        assert body["resource_type"] == "ec2"
        assert body["read_only"] is True
        assert body["count"] == 1
        assert body["resources"][0]["resource_id"] == "i-default-001"

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")