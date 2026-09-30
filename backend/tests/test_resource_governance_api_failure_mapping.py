from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.resource_governance_api as governance_api


class ValueErrorProvider:
    @property
    def provider_name(self):
        return "aws"

    def get_resource(self, resource_type, resource_id):
        raise ValueError("provider validation failed")


class OSErrorProvider:
    @property
    def provider_name(self):
        return "aws"

    def get_resource(self, resource_type, resource_id):
        raise OSError("provider unavailable")


def make_app():
    app = FastAPI()
    app.include_router(governance_api.router)
    return app


def test_governance_api_maps_value_error_to_503(monkeypatch):
    provider = ValueErrorProvider()

    monkeypatch.setattr(
        governance_api.provider_registry,
        "get",
        lambda provider_name: provider,
    )

    client = TestClient(make_app())

    response = client.get(
        "/autonomy/resources/ec2/i-task23-value-error/governance"
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "provider validation failed"
    }


def test_governance_api_maps_os_error_to_503(monkeypatch):
    provider = OSErrorProvider()

    monkeypatch.setattr(
        governance_api.provider_registry,
        "get",
        lambda provider_name: provider,
    )

    client = TestClient(make_app())

    response = client.get(
        "/autonomy/resources/ec2/i-task23-os-error/governance"
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "provider unavailable"
    }


def test_governance_api_keeps_success_contract():
    client = TestClient(make_app())

    response = client.get(
        "/autonomy/resources/ec2/i-task23-success/governance"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["provider"] == "aws"
    assert body["resource_type"] == "ec2"
    assert body["resource_id"] == "i-task23-success"
    assert body["decision"] == "allow"
    assert body["allowed_for_decision"] is True
