import pytest
from fastapi.testclient import TestClient

import main


FOLLOW_UPS = [
    ("/insights", "get_ec2_insights"),
    ("/cpu", "get_ec2_cpu_utilization"),
    ("/network", "get_ec2_network_utilization"),
    ("/status", "get_ec2_instance_status"),
    ("/metrics", "get_ec2_metrics"),
    ("/volumes", "get_ec2_instance_volumes"),
]


@pytest.mark.parametrize("suffix,method_name", FOLLOW_UPS)
@pytest.mark.parametrize("failure_kind", ["exception", "unhealthy", "malformed"])
def test_ec2_follow_up_routes_return_sanitized_503(
    monkeypatch, suffix, method_name, failure_kind
):
    def provider(*args, **kwargs):
        if failure_kind == "exception":
            raise RuntimeError("private account credentials and request data")
        if failure_kind == "unhealthy":
            return {"status": "unhealthy", "error": "private account credentials"}
        return {"unexpected": "private provider response"}

    monkeypatch.setattr(main.aws_service, method_name, provider)
    response = TestClient(main.app).get(
        f"/cloud/aws/ec2/instances/i-12345678{suffix}"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "credentials" not in response.text


def test_ec2_follow_up_success_payload_and_validation_are_preserved(monkeypatch):
    expected = {"service": "ec2", "status": "healthy", "datapoints": []}
    monkeypatch.setattr(
        main.aws_service, "get_ec2_cpu_utilization", lambda *a, **k: expected
    )
    client = TestClient(main.app)

    success = client.get("/cloud/aws/ec2/instances/i-12345678/cpu")
    invalid = client.get("/cloud/aws/ec2/instances/i-12345678/metrics?lookback_hours=25")

    assert success.status_code == 200
    assert success.json() == expected
    assert invalid.status_code == 400


def test_ec2_instance_lookup_exception_is_sanitized_before_tenant_check(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private AWS credentials")

    monkeypatch.setattr(main.aws_service, "get_ec2_instance", fail)
    response = TestClient(main.app).get(
        "/cloud/aws/ec2/instances/i-12345678/insights"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "credentials" not in response.text


def test_ec2_volume_success_and_invalid_instance_id(monkeypatch):
    expected = {
        "service": "ec2", "status": "healthy", "instance_id": "i-12345678",
        "volumes": [{"volume_id": "vol-123", "encrypted": False}],
    }
    monkeypatch.setattr(main.aws_service, "get_ec2_instance_volumes", lambda *a, **k: expected)
    client = TestClient(main.app)

    success = client.get("/cloud/aws/ec2/instances/i-12345678/volumes?region=eu-west-1")
    invalid = client.get("/cloud/aws/ec2/instances/not-an-instance/volumes")

    assert success.status_code == 200
    assert success.json() == expected
    assert invalid.status_code == 400


@pytest.mark.parametrize(
    "path,method_name",
    [
        ("efficiency-insights", "get_ec2_efficiency_insights"),
        ("cost-insights", "get_ec2_cost_insights"),
        ("rightsizing-insights", "get_ec2_rightsizing_insights"),
        ("security-insights", "get_ec2_security_insights"),
    ],
)
def test_ec2_fleet_insight_exceptions_are_sanitized(monkeypatch, path, method_name):
    def fail(*args, **kwargs):
        raise RuntimeError("private AWS credentials")

    monkeypatch.setattr(main.aws_service, method_name, fail)
    response = TestClient(main.app).get(f"/cloud/aws/ec2/{path}")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
