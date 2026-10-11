from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import provider_registry, router


class MalformedRecordsProvider:
    provider_name = "aws"

    def get_ec2_instances(self):
        return {
            "instances": [
                None,
                "invalid-record",
                42,
                {"state": "running"},
                {"instance_id": "i-valid", "state": "running"},
            ]
        }

    def get_s3_buckets(self):
        return {"buckets": []}


def test_inventory_api_skips_malformed_records_and_preserves_valid_records():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    provider_registry.register(MalformedRecordsProvider())

    try:
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
        assert len(body["resources"]) == 1

        resource = body["resources"][0]

        assert resource["resource_id"] == "i-valid"
        assert resource["attributes"] == {
            "instance_id": "i-valid",
            "state": "running",
        }
        assert resource["read_only"] is True

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")
