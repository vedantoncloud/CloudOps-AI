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
    "resource_type",
    [
        "ec2",
        "s3",
    ],
)
def test_provider_exception_returns_sanitized_service_unavailable(resource_type):
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

        assert response.status_code == 503
        assert response.json() == {"detail": "Resource inventory is unavailable"}
        assert "connection failed" not in response.text

    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")


@pytest.mark.parametrize("resource_type", ["ec2", "s3"])
def test_unhealthy_provider_result_is_not_reported_as_empty_inventory(resource_type):
    class UnhealthyProvider:
        provider_name = "aws"

        def get_ec2_instances(self):
            return {"status": "unhealthy", "error": "secret AWS diagnostic"}

        def get_s3_buckets(self):
            return {"status": "unhealthy", "error": "secret AWS diagnostic"}

    if provider_registry.has("aws"):
        provider_registry.unregister("aws")
    provider_registry.register(UnhealthyProvider())

    try:
        app = FastAPI()
        app.include_router(router)
        response = TestClient(app).get(
            f"/autonomy/resources?provider=aws&resource_type={resource_type}"
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "Resource inventory is unavailable"}
        assert "secret AWS diagnostic" not in response.text
    finally:
        if provider_registry.has("aws"):
            provider_registry.unregister("aws")
