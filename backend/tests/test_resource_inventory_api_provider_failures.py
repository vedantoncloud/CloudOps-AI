import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import provider_registry, router


class FailingProvider:
    provider_name = "aws"

    def get_ec2_instances(self):
        raise RuntimeError("EC2 provider connection failed")

    def get_s3_buckets(self):
        raise RuntimeError("S3 provider connection failed")


@pytest.mark.parametrize(
    ("resource_type", "expected_error"),
    [
        ("ec2", "EC2 provider connection failed"),
        ("s3", "S3 provider connection failed"),
    ],
)
def test_provider_failure_returns_internal_server_error(
    resource_type,
    expected_error,
):
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")

    provider_registry.register(FailingProvider())

    try:
        app = FastAPI()
        app.include_router(router)

        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            f"/autonomy/resources?provider=aws&resource_type={resource_type}"
        )

        assert response.status_code == 500
        assert response.text == "Internal Server Error"

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")