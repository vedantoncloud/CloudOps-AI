import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize("provider_result", [
    RuntimeError("internal provider diagnostic"),
    {"service": "ec2", "status": "healthy", "instances": {}},
    {"service": "ec2", "status": "healthy", "instances": ["not-an-instance"]},
])
def test_ec2_inventory_provider_failures_and_malformed_results_are_sanitized(
    monkeypatch, provider_result
):
    def get_instances(*_args, **_kwargs):
        if isinstance(provider_result, Exception):
            raise provider_result
        return provider_result

    monkeypatch.setattr(main.aws_service, "get_ec2_instances", get_instances)

    response = TestClient(main.app).get("/cloud/aws/ec2/instances")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_ec2_inventory_keeps_valid_empty_result(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_ec2_instances",
        lambda *_args, **_kwargs: {
            "service": "ec2", "status": "healthy", "instances": [], "total_instances": 0
        },
    )

    response = TestClient(main.app).get("/cloud/aws/ec2/instances")

    assert response.status_code == 200
    assert response.json()["instances"] == []
