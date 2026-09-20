from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.autonomous_lifecycle import AutonomousLifecycleOrchestrator
import autonomy.lifecycle_api as lifecycle_api


def make_client():
    app = FastAPI()
    app.include_router(lifecycle_api.router)
    lifecycle_api.orchestrator = AutonomousLifecycleOrchestrator()
    return TestClient(app)


def payload(action_id="api-life-1"):
    return {
        "action_id": action_id,
        "action_type": "review_instance_state",
        "resource_type": "ec2_instance",
        "resource_id": "i-123",
        "reason": "API lifecycle test",
        "risk": "low",
        "requires_approval": True,
        "rollback_available": True,
        "dry_run": True,
    }


def test_run_without_approval_waits_for_human():
    client = make_client()
    response = client.post("/autonomy/lifecycle/run", json=payload())

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "awaiting_approval"
    assert data["requires_human_approval"] is True
    assert data["execution"] is None


def test_approve_endpoint_completes_dry_run_lifecycle():
    client = make_client()
    body = payload()
    body["approved_by"] = "operator"

    response = client.post("/autonomy/lifecycle/approve", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "completed"
    assert data["completed"] is True
    assert data["execution"]["dry_run"] is True
    assert data["verification"]["verified"] is True


def test_reject_endpoint_does_not_execute():
    client = make_client()
    body = payload()
    body.update({
        "rejected_by": "operator",
        "rejection_reason": "change not authorized",
    })

    response = client.post("/autonomy/lifecycle/reject", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] in {"blocked", "awaiting_approval"}
    assert data["execution"] is None
    assert data["approval"]["rejected_by"] == "operator"


def test_audit_endpoint_returns_lifecycle_events():
    client = make_client()
    body = payload("api-audit-1")
    body["approved_by"] = "operator"

    run_response = client.post("/autonomy/lifecycle/approve", json=body)
    assert run_response.status_code == 200

    response = client.get("/autonomy/lifecycle/api-audit-1/audit")

    assert response.status_code == 200
    data = response.json()
    assert data["action_id"] == "api-audit-1"
    assert data["count"] >= 3
    assert any(
        event["event"] == "autonomous_lifecycle_started"
        for event in data["events"]
    )


def test_invalid_risk_returns_400():
    client = make_client()
    body = payload()
    body["risk"] = "unknown"

    response = client.post("/autonomy/lifecycle/run", json=body)

    assert response.status_code == 400
    assert "Invalid risk level" in response.json()["detail"]


def test_empty_action_id_is_rejected_by_validation():
    client = make_client()
    body = payload()
    body["action_id"] = ""

    response = client.post("/autonomy/lifecycle/run", json=body)

    assert response.status_code == 422


def test_empty_audit_id_returns_400():
    client = make_client()

    response = client.get("/autonomy/lifecycle/%20/audit")

    assert response.status_code == 400
    assert "action_id" in response.json()["detail"]


def test_run_preserves_idempotency_evidence():
    client = make_client()
    body = payload("api-idempotency-1")
    body["idempotency_key"] = "key-123"

    response = client.post("/autonomy/lifecycle/run", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["evidence"]["action_id"] == "api-idempotency-1"
    assert data["evidence"]["outcome"] == "awaiting_approval"


def test_approve_with_seen_idempotency_does_not_execute():
    client = make_client()
    body = payload("api-idempotency-seen")
    body.update({
        "approved_by": "operator",
        "idempotency_key": "key-seen",
        "idempotency_seen": True,
    })

    response = client.post("/autonomy/lifecycle/approve", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["execution"] is None
    assert data["outcome"] == "blocked"


def test_approve_requires_approver_identity():
    client = make_client()
    body = payload()

    response = client.post("/autonomy/lifecycle/approve", json=body)

    assert response.status_code == 422


def test_reject_requires_reason():
    client = make_client()
    body = payload()
    body["rejected_by"] = "operator"

    response = client.post("/autonomy/lifecycle/reject", json=body)

    assert response.status_code == 422


def test_response_contains_safety_evidence():
    client = make_client()
    body = payload("api-evidence-1")
    body["approved_by"] = "operator"

    response = client.post("/autonomy/lifecycle/approve", json=body)

    assert response.status_code == 200
    data = response.json()
    assert "safety" in data
    assert "evidence" in data["safety"]
    assert data["safety"]["dry_run"] is True
