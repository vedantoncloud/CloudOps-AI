from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import provider_registry, router


class S3ContractProvider:
    provider_name = "aws"

    def get_ec2_instances(self):
        return {"instances": []}

    def get_s3_buckets(self):
        return {
            "buckets": [
                {
                    "name": "cloudops-audit-logs",
                    "region": "ap-south-1",
                    "versioning": "enabled",
                },
                {
                    "bucket_name": "cloudops-backups",
                    "region": "ap-south-1",
                    "versioning": "disabled",
                },
            ]
        }


def test_s3_inventory_api_returns_complete_resource_contract():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    provider_registry.register(S3ContractProvider())

    try:
        app = FastAPI()
        app.include_router(router)

        response = TestClient(app).get(
            "/autonomy/resources?provider=aws&resource_type=s3"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["provider"] == "aws"
        assert body["resource_type"] == "s3"
        assert body["read_only"] is True
        assert body["count"] == 2
        assert len(body["resources"]) == 2

        expected_resources = [
            {
                "provider": "aws",
                "resource_type": "s3",
                "resource_id": "cloudops-audit-logs",
                "attributes": {
                    "name": "cloudops-audit-logs",
                    "region": "ap-south-1",
                    "versioning": "enabled",
                },
                "read_only": True,
            },
            {
                "provider": "aws",
                "resource_type": "s3",
                "resource_id": "cloudops-backups",
                "attributes": {
                    "bucket_name": "cloudops-backups",
                    "region": "ap-south-1",
                    "versioning": "disabled",
                },
                "read_only": True,
            },
        ]

        assert body["resources"] == expected_resources

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")