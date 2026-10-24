from datetime import datetime, timezone

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
    expected = {
        "service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678",
        "metric": "CPUUtilization", "value": None, "datapoints": [],
    }
    monkeypatch.setattr(
        main.aws_service, "get_ec2_cpu_utilization", lambda *a, **k: expected
    )
    client = TestClient(main.app)

    success = client.get("/cloud/aws/ec2/instances/i-12345678/cpu")
    invalid = client.get("/cloud/aws/ec2/instances/i-12345678/metrics?lookback_hours=25")

    assert success.status_code == 200
    assert success.json() == expected
    assert invalid.status_code == 400


@pytest.mark.parametrize(
    "path,method_name,payload",
    [
        ("cpu", "get_ec2_cpu_utilization", {"service": "wrong", "status": "healthy", "instance_id": "i-12345678", "metric": "CPUUtilization", "value": None}),
        ("cpu", "get_ec2_cpu_utilization", {"service": "cloudwatch", "status": "healthy", "instance_id": "i-87654321", "metric": "CPUUtilization", "value": 1}),
        ("cpu", "get_ec2_cpu_utilization", {"service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678", "metric": "CPUUtilization", "value": float("nan")}),
        ("cpu", "get_ec2_cpu_utilization", {"service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678", "metric": "CPUUtilization", "value": None, "datapoints": [{"timestamp": "now", "value": "bad"}]}),
        ("network", "get_ec2_network_utilization", {"service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678", "metrics": {"NetworkIn": 1}, "datapoints": {"NetworkIn": [], "NetworkOut": []}}),
        ("network", "get_ec2_network_utilization", {"service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678", "metrics": {"NetworkIn": 1, "NetworkOut": 2}, "datapoints": {"NetworkIn": [], "NetworkOut": [None]}}),
    ],
)
def test_ec2_cpu_and_network_reject_malformed_healthy_payload(monkeypatch, path, method_name, payload):
    monkeypatch.setattr(main.aws_service, method_name, lambda *a, **k: payload)

    response = TestClient(main.app).get(f"/cloud/aws/ec2/instances/i-12345678/{path}")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_ec2_network_preserves_valid_payload(monkeypatch):
    expected = {
        "service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678",
        "metrics": {"NetworkIn": None, "NetworkOut": 12.5},
        "datapoints": {"NetworkIn": [], "NetworkOut": [{"timestamp": "2026-10-24T12:00:00+00:00", "value": 12.5}]},
    }
    monkeypatch.setattr(main.aws_service, "get_ec2_network_utilization", lambda *a, **k: expected)

    response = TestClient(main.app).get("/cloud/aws/ec2/instances/i-12345678/network")

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"service": "wrong", "status": "healthy", "instance_id": "i-12345678", "cpu": {}, "network": {}, "instance_status": {}},
        {"service": "ec2", "status": "healthy", "instance_id": "i-87654321", "cpu": {}, "network": {}, "instance_status": {}},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "cpu": [], "network": {}, "instance_status": {}},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "cpu": {}, "network": {}, "instance_status": None},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "cpu": {}, "network": {}, "instance_status": {}, "status_checks": []},
    ],
)
def test_ec2_metrics_rejects_malformed_healthy_payload(monkeypatch, payload):
    monkeypatch.setattr(main.aws_service, "get_ec2_metrics", lambda *a, **k: payload)

    response = TestClient(main.app).get("/cloud/aws/ec2/instances/i-12345678/metrics")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


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


@pytest.mark.parametrize(
    "payload",
    [
        {"service": "wrong", "status": "healthy", "instance_id": "i-12345678", "instance_status": None, "system_status": None, "state": None, "events": []},
        {"service": "ec2", "status": "healthy", "instance_id": "i-87654321", "instance_status": "ok", "system_status": "ok", "state": "running", "events": []},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "instance_status": [], "system_status": "ok", "state": "running", "events": []},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "instance_status": None, "system_status": None, "state": None, "events": [None]},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "instance_status": None, "system_status": None, "state": None, "events": [{"PrivateField": "leak"}]},
    ],
)
def test_ec2_instance_status_rejects_malformed_healthy_payload(monkeypatch, payload):
    monkeypatch.setattr(main.aws_service, "get_ec2_instance_status", lambda *a, **k: payload)

    response = TestClient(main.app).get("/cloud/aws/ec2/instances/i-12345678/status")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_ec2_instance_status_preserves_valid_payload(monkeypatch):
    expected = {
        "service": "ec2", "status": "healthy", "instance_id": "i-12345678",
        "instance_status": "ok", "system_status": "ok", "state": "running",
        "events": [{
            "Code": "instance-stop", "Description": "Scheduled stop",
            "NotBefore": datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
        }],
    }
    monkeypatch.setattr(main.aws_service, "get_ec2_instance_status", lambda *a, **k: expected)

    response = TestClient(main.app).get("/cloud/aws/ec2/instances/i-12345678/status")

    assert response.status_code == 200
    assert response.json()["events"] == [{
        "Code": "instance-stop", "Description": "Scheduled stop",
        "NotBefore": "2026-10-24T12:00:00+00:00",
    }]


@pytest.mark.parametrize(
    "instance",
    [
        [],
        {"tags": {}},
        {"instance_id": "i-87654321", "tags": {}},
        {"instance_id": "i-12345678", "tags": []},
    ],
)
def test_ec2_instance_detail_rejects_malformed_healthy_provider_records(monkeypatch, instance):
    monkeypatch.setattr(
        main.aws_service,
        "get_ec2_instance",
        lambda *_args, **_kwargs: {"status": "healthy", "instance": instance},
    )

    response = TestClient(main.app).get("/cloud/aws/ec2/instances/i-12345678")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_ec2_instance_detail_keeps_missing_instance_as_not_found(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_ec2_instance",
        lambda *_args, **_kwargs: {"status": "healthy", "instance": None},
    )

    response = TestClient(main.app).get("/cloud/aws/ec2/instances/i-12345678")

    assert response.status_code == 404
    assert response.json() == {"detail": "EC2 instance not found"}


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
    "payload",
    [
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "volumes": {}},
        {"service": "ec2", "status": "healthy", "instance_id": "i-87654321", "volumes": []},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "volumes": [{"volume_id": "vol-1", "encrypted": "yes"}]},
        {"service": "ec2", "status": "healthy", "instance_id": "i-12345678", "volumes": [{"volume_id": "vol-1", "attachments": [None]}]},
    ],
)
def test_ec2_volume_malformed_healthy_payload_is_sanitized(monkeypatch, payload):
    monkeypatch.setattr(main.aws_service, "get_ec2_instance_volumes", lambda *a, **k: payload)

    response = TestClient(main.app).get("/cloud/aws/ec2/instances/i-12345678/volumes")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


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
