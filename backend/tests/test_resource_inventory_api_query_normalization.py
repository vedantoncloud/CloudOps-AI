from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import provider_registry, router


class NormalizationProvider:
    provider_name = "aws"

    def get_ec2_instances(self):
        return {
            "instances": [
                {
                    "instance_id": "i-normalized",
                    "state": "running",
                }
            ]
        }

    def get_s3_buckets(self):
        return {"buckets": []}


def test_inventory_api_trims_and_normalizes_query_parameters():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    provider_registry.register(NormalizationProvider())

    try:
        app = FastAPI()
        app.include_router(router)

        response = TestClient(app).get(
            "/autonomy/resources?provider=%20AWS%20&resource_type=%20EC2%20"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["provider"] == "aws"
        assert body["resource_type"] == "ec2"
        assert body["count"] == 1
        assert body["resources"][0]["resource_id"] == "i-normalized"

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")
