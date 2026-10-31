from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

import autonomy.autonomous_control_plane_api as control_plane_api
from auth import AccessControlMiddleware, Principal
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


def test_action_identity_is_isolated_by_tenant_and_operation():
    request = ControlPlaneRunRequest(
        resource_type="ec2",
        resource_id="i-12345678",
        action_type="review_instance_state",
        idempotency_key="retry-1",
    )

    tenant_a = _action(request, tenant_id="tenant-a")
    tenant_b = _action(request, tenant_id="tenant-b")
    different_action = _action(
        ControlPlaneRunRequest(
            resource_type="ec2",
            resource_id="i-12345678",
            action_type="investigate_cpu_capacity",
            idempotency_key="retry-1",
        ),
        tenant_id="tenant-a",
    )
    different_key = _action(
        ControlPlaneRunRequest(
            resource_type="ec2",
            resource_id="i-12345678",
            action_type="review_instance_state",
            idempotency_key="retry-2",
        ),
        tenant_id="tenant-a",
    )

    assert tenant_a.action_id != tenant_b.action_id
    assert tenant_a.action_id != different_action.action_id
    assert tenant_a.action_id != different_key.action_id
    assert tenant_a.action_id == _action(request, tenant_id="tenant-a").action_id


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


def test_run_attributes_actor_and_ignores_caller_supplied_reviewer(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"operator-token": Principal("operator-17", "operator", "tenant-a")},
    )
    observed = {}

    def run(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            outcome="awaiting_approval",
            executed=False,
            governed=SimpleNamespace(evidence={"decision": "allow"}),
            lifecycle=None,
            evidence={"actor": kwargs["actor_id"]},
        )

    monkeypatch.setattr(control_plane_api.control_plane, "run", run)
    response = TestClient(app).post(
        "/autonomy/control-plane/run",
        headers={"Authorization": "Bearer operator-token"},
        json={
            "resource_type": "ec2",
            "resource_id": "i-12345678",
            "action_type": "restart_instance",
            "approved_by": "forged-admin",
        },
    )

    assert response.status_code == 200
    assert observed["actor_id"] == "operator-17"
    assert observed["tenant_id"] == "tenant-a"
    assert observed["approved_by"] == "operator-17"
    assert observed["rejected_by"] is None
    assert response.json()["evidence"]["actor"] == "operator-17"


def test_control_plane_rejection_without_reason_fails_before_lifecycle(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"operator-token": Principal("operator-17", "operator", "tenant-a")},
    )
    monkeypatch.setattr(
        control_plane_api.control_plane,
        "run",
        lambda **kwargs: pytest.fail("invalid rejection must not enter lifecycle"),
    )

    response = TestClient(app).post(
        "/autonomy/control-plane/run",
        headers={"Authorization": "Bearer operator-token"},
        json={
            "resource_type": "ec2",
            "resource_id": "i-12345678",
            "action_type": "restart_instance",
            "rejected_by": "forged-admin",
        },
    )

    assert response.status_code == 400
    assert "rejection_reason is required" in response.json()["detail"]
