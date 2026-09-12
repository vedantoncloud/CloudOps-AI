from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.audit_api import audit_trail, router as audit_router
from autonomy.control_loop_api import router as control_loop_router
from autonomy.control_plane_api import router as control_plane_router
from autonomy.gitops_api import registry as gitops_registry
from autonomy.gitops_api import router as gitops_router


app = FastAPI()
app.include_router(control_plane_router)
app.include_router(control_loop_router)
app.include_router(gitops_router)
app.include_router(audit_router)

client = TestClient(app)


def setup_function():
    gitops_registry.clear()
    audit_trail.clear()


def evaluate_action(action_id="trace-action-1"):
    return client.post(
        "/autonomy/control-loop/evaluate",
        json={
            "action_id": action_id,
            "action_type": "investigate_cpu_capacity",
            "resource_type": "ec2",
            "resource_id": "i-trace-123",
            "reason": "High CPU utilization detected",
            "risk": "medium",
            "requires_approval": True,
            "field": "instance_type",
            "desired_value": "t3.large",
            "current_value": "t3.medium",
        },
    )


def test_action_trace_returns_complete_gitops_and_audit_history():
    evaluate = evaluate_action()

    assert evaluate.status_code == 200
    change_id = evaluate.json()["gitops_change_id"]

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
    assert apply.json()["status"] == "applied"

    verify = client.post(
        f"/autonomy/gitops/changes/{change_id}/verify",
        json={
            "observed_values": {
                "infrastructure/i-trace-123/instance_type": "t3.large"
            }
        },
    )
    assert verify.status_code == 200
    assert verify.json()["verified"] is True

    trace = client.get(
        "/autonomy/control-plane/actions/trace-action-1/trace"
    )

    assert trace.status_code == 200

    data = trace.json()

    assert data["action_id"] == "trace-action-1"
    assert data["status"] == "verified"

    assert data["gitops"] is not None
    assert data["gitops"]["change_id"] == change_id
    assert data["gitops"]["source_action_id"] == "trace-action-1"
    assert data["gitops"]["status"] == "verified"
    assert data["gitops"]["requires_approval"] is True
    assert data["gitops"]["approved_by"] == "operator"
    assert data["gitops"]["change_count"] == 1

    change = data["gitops"]["changes"][0]

    assert change["resource_type"] == "infrastructure"
    assert change["resource_id"] == "i-trace-123"
    assert change["field"] == "instance_type"
    assert change["desired_value"] == "t3.large"
    assert change["current_value"] == "t3.medium"

    event_names = [
        event["event"]
        for event in data["audit_events"]
    ]

    assert event_names == [
        "gitops_change_registered",
        "control_loop_evaluated",
        "gitops_change_approved",
        "gitops_change_applied",
        "gitops_change_verified",
    ]


def test_action_trace_is_read_only():
    evaluate = evaluate_action("trace-read-only")

    assert evaluate.status_code == 200
    change_id = evaluate.json()["gitops_change_id"]

    trace = client.get(
        "/autonomy/control-plane/actions/trace-read-only/trace"
    )

    assert trace.status_code == 200
    assert trace.json()["status"] == "pending_approval"

    change = gitops_registry.require(change_id)

    assert change.status.value == "pending_approval"


def test_action_trace_includes_failed_verification():
    evaluate = evaluate_action("trace-failed")

    assert evaluate.status_code == 200
    change_id = evaluate.json()["gitops_change_id"]

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

    verify = client.post(
        f"/autonomy/gitops/changes/{change_id}/verify",
        json={
            "observed_values": {
                "infrastructure/i-trace-123/instance_type": "t3.medium"
            }
        },
    )

    assert verify.status_code == 200
    assert verify.json()["verified"] is False
    assert verify.json()["status"] == "failed"

    trace = client.get(
        "/autonomy/control-plane/actions/trace-failed/trace"
    )

    assert trace.status_code == 200
    assert trace.json()["status"] == "failed"

    event_names = [
        event["event"]
        for event in trace.json()["audit_events"]
    ]

    assert "gitops_verification_failed" in event_names


def test_action_trace_returns_404_for_unknown_action():
    trace = client.get(
        "/autonomy/control-plane/actions/does-not-exist/trace"
    )

    assert trace.status_code == 404
    assert trace.json()["detail"] == (
        "Action trace not found: does-not-exist"
    )
