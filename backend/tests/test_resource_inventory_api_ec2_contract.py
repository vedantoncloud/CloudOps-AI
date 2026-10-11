from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import provider_registry, router


class EC2ContractProvider:
    provider_name = "aws"

    def get_ec2_instances(self):
        return {
            "instances": [
                {
                    "instance_id": "i-prod-001",
                    "state": "running",
                    "instance_type": "t3.medium",
                    "region": "ap-south-1",
                    "tags": {"Environment": "production"},
                },
                {
                    "instance_id": "i-dev-002",
                    "state": "stopped",
                    "instance_type": "t3.micro",
                    "region": "ap-south-1",
                    "tags": {"Environment": "development"},
                },
            ]
        }

    def get_s3_buckets(self):
        return {"buckets": []}


def test_ec2_inventory_api_returns_complete_resource_contract():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    provider_registry.register(EC2ContractProvider())

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
        assert body["count"] == 2
        assert len(body["resources"]) == 2

        expected_resources = [
            {
                "provider": "aws",
                "resource_type": "ec2",
                "resource_id": "i-prod-001",
                "attributes": {
                    "instance_id": "i-prod-001",
                    "state": "running",
                    "instance_type": "t3.medium",
                    "region": "ap-south-1",
                    "tags": {"Environment": "production"},
                },
                "read_only": True,
            },
            {
                "provider": "aws",
                "resource_type": "ec2",
                "resource_id": "i-dev-002",
                "attributes": {
                    "instance_id": "i-dev-002",
                    "state": "stopped",
                    "instance_type": "t3.micro",
                    "region": "ap-south-1",
                    "tags": {"Environment": "development"},
                },
                "read_only": True,
            },
        ]

        assert body["resources"] == expected_resources

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")