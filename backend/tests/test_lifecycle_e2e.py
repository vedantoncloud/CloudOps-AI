from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.lifecycle_api import orchestrator, router as lifecycle_router


def make_app():
    app = FastAPI()
    app.include_router(lifecycle_router)
    return app


def setup_function():
    orchestrator.audit_trail.clear()


def payload(action_id="e2e-lifecycle-1"):
    return {
        "action_id": action_id,
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-lifecycle-e2e",
        "reason": "Validate autonomous lifecycle",
        "risk": "medium",
        "requires_approval": True,
        "rollback_available": True,
        "dry_run": True,
    }


def test_unapproved_action_waits_for_human_approval():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/lifecycle/run",
        json=payload(),
    )

    assert response.status_code == 200
    data = response.json()

    assert data["outcome"] == "awaiting_approval"
    assert data["approval"]["status"] == "pending"
    assert data["execution"] is None
    assert data["verification"] is None
    assert data["evidence"]["requires_human_approval"] is True


def test_approved_action_completes_dry_run_lifecycle():
    client = TestClient(make_app())

    body = payload("e2e-lifecycle-approved")
    body["approved_by"] = "operator"

    response = client.post(
        "/autonomy/lifecycle/approve",
        json=body,
    )

    assert response.status_code == 200
    data = response.json()

    assert data["outcome"] == "completed"
    assert data["approval"]["status"] == "approved"
    assert data["approval"]["approved_by"] == "operator"
    assert data["execution"]["executed"] is False
    assert data["execution"]["successful"] is True
    assert data["execution"]["dry_run"] is True
    assert data["verification"]["verified"] is True

    events = client.get(
        "/autonomy/lifecycle/e2e-lifecycle-approved/audit"
    )
    assert events.status_code == 200
    event_names = [event["event"] for event in events.json()["events"]]

    assert "autonomous_lifecycle_started" in event_names
    assert "autonomous_safety_evaluated" in event_names
    assert "action_verification_completed" in event_names
    assert "autonomous_lifecycle_completed" in event_names


def test_rejected_action_never_executes():
    client = TestClient(make_app())

    body = payload("e2e-lifecycle-rejected")
    body.update({
        "rejected_by": "operator",
        "rejection_reason": "Change is not authorized",
    })

    response = client.post(
        "/autonomy/lifecycle/reject",
        json=body,
    )

    assert response.status_code == 200
    data = response.json()

    assert data["approval"]["status"] == "rejected"
    assert data["approval"]["rejected_by"] == "operator"
    assert data["approval"]["reason"] == "Change is not authorized"
    assert data["execution"] is None
    assert data["verification"] is None


def test_seen_idempotency_is_blocked_and_never_executes():
    client = TestClient(make_app())

    body = payload("e2e-lifecycle-idempotency")
    body.update({
        "approved_by": "operator",
        "idempotency_key": "e2e-key-seen",
        "idempotency_seen": True,
    })

    response = client.post(
        "/autonomy/lifecycle/approve",
        json=body,
    )

    assert response.status_code == 200
    data = response.json()

    assert data["outcome"] == "blocked"
    assert data["safety"]["decision"] == "deny"
    assert data["safety"]["execution_allowed"] is False
    assert data["execution"] is None
    assert data["verification"] is None


def test_lifecycle_audit_preserves_safety_and_approval_evidence():
    client = TestClient(make_app())

    body = payload("e2e-lifecycle-evidence")
    body["approved_by"] = "operator"

    response = client.post(
        "/autonomy/lifecycle/approve",
        json=body,
    )

    assert response.status_code == 200
    data = response.json()

    assert data["evidence"]["approval_status"] == "approved"
    assert data["evidence"]["approved_by"] == "operator"
    assert "safety_decision" in data["evidence"]
    assert "safety_evidence" in data["evidence"]

    audit = client.get(
        "/autonomy/lifecycle/e2e-lifecycle-evidence/audit"
    )
    assert audit.status_code == 200

    events = audit.json()["events"]
    safety_events = [
        event
        for event in events
        if event["event"] == "autonomous_safety_evaluated"
    ]
    assert len(safety_events) == 1
    assert safety_events[0]["details"]["approval_status"] == "approved"
    assert "safety_evidence" in safety_events[0]["details"]
