from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from autonomy.autonomous_control_plane_api import (
    ControlPlaneRunRequest,
    _action,
    router,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_control_plane_api_route_exists(client):
    response = client.post(
        "/autonomy/control-plane/run",
        json={
            "resource_type": "ec2",
            "resource_id": "i-1",
            "action_type": "restart_instance",
            "reason": "test",
        },
    )
    assert response.status_code in {200, 400}


def test_invalid_risk_returns_400(client):
    response = client.post(
        "/autonomy/control-plane/run",
        json={
            "resource_type": "ec2",
            "resource_id": "i-2",
            "action_type": "restart_instance",
            "reason": "test",
            "risk": "not-a-risk",
        },
    )
    assert response.status_code == 400
    assert "Invalid risk" in response.json()["detail"]


def test_request_defaults_to_dry_run():
    request = ControlPlaneRunRequest(
        resource_type="ec2",
        resource_id="i-2",
        action_type="restart_instance",
    )
    assert request.dry_run is True
    assert request.provider == "aws"


def test_action_target_is_bound_to_resource():
    request = ControlPlaneRunRequest(
        resource_type="ec2",
        resource_id="i-3",
        action_type="restart_instance",
        target={"name": "demo"},
    )
    action = _action(request)
    assert action.target.resource_id == "i-3"
    assert action.target.resource_type == "ec2"


def test_unknown_provider_returns_400(client):
    response = client.post(
        "/autonomy/control-plane/run",
        json={
            "provider": "unknown",
            "resource_type": "ec2",
            "resource_id": "i-4",
            "action_type": "restart_instance",
        },
    )
    assert response.status_code == 400
    assert "Unknown provider" in response.json()["detail"]


@pytest.mark.parametrize(
    "field",
    ["provider", "resource_type", "resource_id", "action_type"],
)
def test_empty_required_fields_are_rejected(field):
    payload = {
        "provider": "aws",
        "resource_type": "ec2",
        "resource_id": "i-5",
        "action_type": "restart_instance",
    }
    payload[field] = "   "

    with pytest.raises(ValidationError):
        ControlPlaneRunRequest(**payload)


def test_required_fields_are_trimmed():
    request = ControlPlaneRunRequest(
        provider="  aws  ",
        resource_type="  ec2  ",
        resource_id="  i-6  ",
        action_type="  restart_instance  ",
        reason="  investigate  ",
        risk="  HIGH  ",
        idempotency_key="  key-6  ",
    )

    assert request.provider == "aws"
    assert request.resource_type == "ec2"
    assert request.resource_id == "i-6"
    assert request.action_type == "restart_instance"
    assert request.reason == "investigate"
    assert request.risk == "high"
    assert request.idempotency_key == "key-6"


def test_blank_idempotency_key_becomes_none():
    request = ControlPlaneRunRequest(
        resource_type="ec2",
        resource_id="i-7",
        action_type="restart_instance",
        idempotency_key="   ",
    )
    assert request.idempotency_key is None


def test_blank_reason_uses_safe_default():
    request = ControlPlaneRunRequest(
        resource_type="ec2",
        resource_id="i-8",
        action_type="restart_instance",
        reason="   ",
    )
    assert request.reason == "Autonomous control-plane request"
