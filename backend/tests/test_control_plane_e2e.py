from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.audit_api import audit_trail
from autonomy.control_loop_api import router as control_loop_router
from autonomy.gitops_api import registry as gitops_registry
from autonomy.gitops_api import router as gitops_router


def make_app():
    app = FastAPI()
    app.include_router(control_loop_router)
    app.include_router(gitops_router)
    return app


def setup_function():
    gitops_registry.clear()
    audit_trail.clear()


def test_end_to_end_control_plane_lifecycle():
    client = TestClient(make_app())

    evaluate = client.post(
        "/autonomy/control-loop/evaluate",
        json={
            "action_id": "e2e-action-1",
            "action_type": "investigate_cpu_capacity",
            "resource_type": "ec2",
            "resource_id": "i-e2e-123",
            "reason": "High CPU utilization detected",
            "risk": "medium",
            "requires_approval": True,
            "field": "instance_type",
            "desired_value": "t3.large",
            "current_value": "t3.medium",
        },
    )

    assert evaluate.status_code == 200

    decision = evaluate.json()

    assert decision["gitops_created"] is True
    assert decision["gitops_change_id"] is not None
    assert decision["gitops_status"] == "pending_approval"
    change_id = decision["gitops_change_id"]

    audit_events = audit_trail.get_events("e2e-action-1")
    assert any(
        event.event == "gitops_change_registered"
        for event in audit_events
    )
    assert any(
        event.event == "control_loop_evaluated"
        for event in audit_events
    )

    approve = client.post(
        f"/autonomy/gitops/changes/{change_id}/approve",
        json={"approved_by": "operator"},
    )

    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    apply = client.post(
        f"/autonomy/gitops/changes/{change_id}/apply",
        json={"dry_run": True},
    )

    assert apply.status_code == 200
    assert apply.json()["success"] is True
    assert apply.json()["dry_run"] is True
    assert apply.json()["status"] == "applied"

    verify = client.post(
        f"/autonomy/gitops/changes/{change_id}/verify",
        json={
            "observed_values": {
                "infrastructure/i-e2e-123/instance_type": "t3.large"
            }
        },
    )

    assert verify.status_code == 200
    assert verify.json()["verified"] is True
    assert verify.json()["status"] == "verified"

    events = audit_trail.get_events("e2e-action-1")
    event_names = [event.event for event in events]

    assert event_names == [
        "gitops_change_registered",
        "control_loop_evaluated",
        "gitops_change_approved",
        "gitops_change_applied",
        "gitops_change_verified",
    ]


def test_end_to_end_rejection_is_audited():
    client = TestClient(make_app())

    evaluate = client.post(
        "/autonomy/control-loop/evaluate",
        json={
            "action_id": "e2e-reject-1",
            "action_type": "investigate_cpu_capacity",
            "resource_type": "ec2",
            "resource_id": "i-e2e-reject",
            "reason": "Capacity review",
            "risk": "medium",
            "requires_approval": True,
            "field": "instance_type",
            "desired_value": "t3.large",
            "current_value": "t3.medium",
        },
    )

    assert evaluate.status_code == 200

    change_id = evaluate.json()["gitops_change_id"]
    assert change_id is not None

    reject = client.post(
        f"/autonomy/gitops/changes/{change_id}/reject",
        json={
            "rejected_by": "operator",
            "reason": "Change is not currently required",
        },
    )

    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    events = audit_trail.get_events("e2e-reject-1")
    event_names = [event.event for event in events]

    assert "gitops_change_registered" in event_names
    assert "control_loop_evaluated" in event_names
    assert "gitops_change_rejected" in event_names


def test_end_to_end_failed_verification_is_audited():
    client = TestClient(make_app())

    evaluate = client.post(
        "/autonomy/control-loop/evaluate",
        json={
            "action_id": "e2e-fail-1",
            "action_type": "investigate_cpu_capacity",
            "resource_type": "ec2",
            "resource_id": "i-e2e-fail",
            "reason": "Capacity review",
            "risk": "medium",
            "requires_approval": True,
            "field": "instance_type",
            "desired_value": "t3.large",
            "current_value": "t3.medium",
        },
    )

    assert evaluate.status_code == 200

    change_id = evaluate.json()["gitops_change_id"]
    assert change_id is not None

    approve = client.post(
        f"/autonomy/gitops/changes/{change_id}/approve",
        json={"approved_by": "operator"},
    )
    assert approve.status_code == 200

    apply = client.post(
        f"/autonomy/gitops/changes/{change_id}/apply",
        json={"dry_run": True},
    )
    assert apply.status_code == 200
    assert apply.json()["success"] is True

    verify = client.post(
        f"/autonomy/gitops/changes/{change_id}/verify",
        json={
            "observed_values": {
                "ec2/i-e2e-fail/instance_type": "t3.medium"
            }
        },
    )

    assert verify.status_code == 200
    assert verify.json()["verified"] is False
    assert verify.json()["status"] == "failed"

    events = audit_trail.get_events("e2e-fail-1")
    assert any(
        event.event == "gitops_verification_failed"
        for event in events
    )

