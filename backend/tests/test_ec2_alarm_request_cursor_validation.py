import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize("cursor", ["", "   ", "x" * 4097])
def test_ec2_alarm_endpoint_rejects_invalid_request_cursor_before_provider_call(
    monkeypatch, cursor
):
    called = False

    def unexpected_provider_call(*args, **kwargs):
        nonlocal called
        called = True
        pytest.fail("invalid alarm cursor must be rejected before AWS is called")

    monkeypatch.setattr(main, "_require_tenant_ec2_instance", lambda *args: None)
    monkeypatch.setattr(main.aws_service, "get_ec2_alarms", unexpected_provider_call)

    response = TestClient(main.app).get(
        "/cloud/aws/ec2/instances/i-12345678/alarms",
        params={"next_token": cursor},
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith(
        "next_token must contain 1 to 4096"
    )
    assert called is False
