import pytest
from fastapi.testclient import TestClient

import main
import services.aws_service as aws_service_module


@pytest.mark.parametrize("result", [None, [], {"provider": "AWS", "status": "connected"},
                                   {"provider": "other", "status": "connected", "services": {}, "message": "ok"},
                                   {"provider": "AWS", "status": "unknown", "services": {}, "message": "ok"}])
def test_aws_status_rejects_malformed_provider_payloads(monkeypatch, result):
    monkeypatch.setattr(main.aws_service, "get_status", lambda: result)

    response = TestClient(main.app).get("/cloud/aws/status")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS status is unavailable"}


def test_aws_status_sanitizes_provider_exceptions(monkeypatch):
    def fail():
        raise RuntimeError("private endpoint and credentials")

    monkeypatch.setattr(main.aws_service, "get_status", fail)

    response = TestClient(main.app).get("/cloud/aws/status")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS status is unavailable"}
    assert "credentials" not in response.text


def test_aws_status_preserves_disconnected_provider_response(monkeypatch):
    result = {
        "provider": "AWS", "status": "disconnected",
        "message": "Unable to connect to AWS services", "error": "diagnostic",
    }
    monkeypatch.setattr(main.aws_service, "get_status", lambda: result)

    response = TestClient(main.app).get("/cloud/aws/status")

    assert response.status_code == 200
    assert response.json() == result


@pytest.mark.parametrize("page", [
    None,
    [],
    {"Reservations": "not-a-list"},
    {"Reservations": [None]},
    {"Reservations": [{"Instances": {}}]},
    {"Reservations": [{"Instances": [None]}]},
    {"Reservations": [{"Instances": [{"State": "running"}]}]},
    {"Reservations": [{"Instances": [{"State": {"Name": 7}}]}]},
])
def test_aws_status_fails_closed_on_malformed_ec2_page_shapes(monkeypatch, page):
    class FakeSts:
        def get_caller_identity(self):
            return {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:role/test"}

    class FakeEc2:
        def describe_instances(self, **_kwargs):
            return page

    monkeypatch.setattr(
        aws_service_module, "_aws_client",
        lambda service, **_kwargs: FakeSts() if service == "sts" else FakeEc2(),
    )

    result = main.aws_service.get_status()

    assert result["status"] == "disconnected"
    assert result["message"] == "Unable to connect to AWS services"
    assert result["error"].startswith("Malformed EC2")


def test_aws_status_counts_well_formed_ec2_instance_states(monkeypatch):
    class FakeSts:
        def get_caller_identity(self):
            return {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:role/test"}

    class FakeEc2:
        def describe_instances(self, **_kwargs):
            return {"Reservations": [{
                "Instances": [
                    {"State": {"Name": "running"}},
                    {"State": {"Name": "stopped"}},
                    {"State": {"Name": "pending"}},
                ]
            }]}

    monkeypatch.setattr(
        aws_service_module, "_aws_client",
        lambda service, **_kwargs: FakeSts() if service == "sts" else FakeEc2(),
    )

    result = main.aws_service.get_status()

    assert result["status"] == "connected"
    assert result["services"]["ec2"] == {
        "status": "healthy", "total_instances": 3,
        "running_instances": 1, "stopped_instances": 1,
    }
