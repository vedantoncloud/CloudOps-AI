from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy import lifecycle_api
from autonomy.autonomous_lifecycle import AutonomousLifecycleOrchestrator
from main import app as application


def make_client():
    app = FastAPI()
    app.include_router(lifecycle_api.router)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={
            "operator-token": Principal("operator-1", "operator", "tenant-a"),
            "other-token": Principal("operator-2", "operator", "tenant-b"),
            "colleague-token": Principal("operator-3", "operator", "tenant-a"),
            "reader-token": Principal("reader-1", "reader", "tenant-a"),
        },
    )
    lifecycle_api.orchestrator = AutonomousLifecycleOrchestrator()
    lifecycle_api._action_owners.clear()
    return TestClient(app)


def action_payload(action_id="app-lifecycle-1"):
    return {
        "action_id": action_id,
        "action_type": "review_instance_state",
        "resource_type": "ec2_instance",
        "resource_id": "i-12345678",
        "reason": "Review requested instance",
        "risk": "low",
        "requires_approval": True,
        "rollback_available": True,
        "dry_run": True,
        "approved_by": "forged-reviewer",
    }


def test_lifecycle_routes_are_mounted_on_application():
    paths = {route.path for route in application.routes}
    assert "/autonomy/lifecycle/run" in paths
    assert "/autonomy/lifecycle/approve" in paths
    assert "/autonomy/lifecycle/reject" in paths


def test_approval_uses_authenticated_actor_and_audit_records_it():
    client = make_client()
    response = client.post(
        "/autonomy/lifecycle/approve",
        json=action_payload(),
        headers={"Authorization": "Bearer operator-token"},
    )

    assert response.status_code == 200
    assert response.json()["approval"]["approved_by"] == "operator-1"
    audit = client.get(
        "/autonomy/lifecycle/app-lifecycle-1/audit",
        headers={"Authorization": "Bearer operator-token"},
    )
    assert audit.status_code == 200
    assert all(event["actor_id"] == "operator-1" for event in audit.json()["events"])


def test_lifecycle_audit_is_hidden_from_other_tenants_and_unknown_actions():
    client = make_client()
    headers = {"Authorization": "Bearer operator-token"}
    assert client.post("/autonomy/lifecycle/run", json=action_payload(), headers=headers).status_code == 200

    foreign = client.get(
        "/autonomy/lifecycle/app-lifecycle-1/audit",
        headers={"Authorization": "Bearer other-token"},
    )
    missing = client.get(
        "/autonomy/lifecycle/does-not-exist/audit",
        headers={"Authorization": "Bearer operator-token"},
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()

    same_tenant = client.get(
        "/autonomy/lifecycle/app-lifecycle-1/audit",
        headers={"Authorization": "Bearer colleague-token"},
    )
    assert same_tenant.status_code == 200


def test_reader_cannot_approve_lifecycle_action():
    response = make_client().post(
        "/autonomy/lifecycle/approve",
        json=action_payload(),
        headers={"Authorization": "Bearer reader-token"},
    )
    assert response.status_code == 403
