import pytest
from fastapi.testclient import TestClient

import main


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
