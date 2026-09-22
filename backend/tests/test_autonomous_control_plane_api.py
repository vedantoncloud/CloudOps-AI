from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.autonomous_control_plane_api import (
    ControlPlaneRunRequest,
    _action,
    router,
)


def test_control_plane_api_route_exists():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post(
        "/autonomy/control-plane/run",
        json={
            "resource_type": "ec2",
            "resource_id": "i-1",
            "action_type": "restart_instance",
            "reason": "test",
        },
    )

    assert response.status_code in {200, 400}


def test_invalid_risk_returns_400():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post(
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


def test_unknown_provider_returns_400():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post(
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
