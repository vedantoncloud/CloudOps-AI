from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy import control_loop_api
from autonomy.audit import AuditTrail
from autonomy.control_loop_api import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def make_payload(**overrides):
    payload = {
        "action_id": "action-api-1",
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-api-123",
        "reason": "High CPU utilization detected",
        "risk": "medium",
        "requires_approval": True,
        "field": "instance_type",
        "desired_value": "t3.large",
        "current_value": "t3.medium",
    }
    payload.update(overrides)
    return payload


def test_control_loop_api_returns_decision():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["action_id"] == "action-api-1"
    assert data["resource_id"] == "i-api-123"
    assert data["recommendation"] == "review"
    assert data["risk"] == "medium"
    assert data["requires_human_review"] is True


def test_control_loop_api_creates_gitops_proposal():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(),
    )

    data = response.json()

    assert data["gitops_created"] is True
    assert data["gitops_change_id"] is not None
    assert data["gitops_status"] == "pending_approval"


def test_control_loop_api_preserves_evidence():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(),
    )

    data = response.json()

    assert isinstance(data["evidence"], dict)


def test_control_loop_api_accepts_low_risk_non_approval_action():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(
            risk="low",
            requires_approval=False,
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["gitops_created"] is True


def test_control_loop_api_rejects_missing_action_id():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(
            action_id="",
        ),
    )

    assert response.status_code == 422


def test_control_loop_api_rejects_missing_resource_id():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(
            resource_id="",
        ),
    )

    assert response.status_code == 422


def test_control_loop_api_rejects_missing_field():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(
            field="",
        ),
    )

    assert response.status_code == 422


def test_control_loop_api_does_not_execute_infrastructure_changes():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["gitops_status"] == "pending_approval"


def test_control_loop_audit_events_include_authenticated_actor(monkeypatch):
    trail = AuditTrail()
    monkeypatch.setattr(control_loop_api, "audit_trail", trail)
    monkeypatch.setattr(control_loop_api.gitops_registry, "audit_trail", trail)
    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"operator-token": Principal("operator-17", "operator", "tenant-a")},
    )
    app.include_router(router)

    response = TestClient(app).post(
        "/autonomy/control-loop/evaluate",
        json=make_payload(action_id="actor-attributed-action"),
        headers={"Authorization": "Bearer operator-token"},
    )

    assert response.status_code == 200
    events = trail.get_events("actor-attributed-action")
    assert events
    assert all(event.actor_id == "operator-17" for event in events)
    assert any(
        event.event == "gitops_change_registered" and event.actor_id == "operator-17"
        for event in events
    )
