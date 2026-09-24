from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.autonomous_run_api as api


class FakeRunner:
    def __init__(self, outcome: str):
        self.outcome = outcome
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)

        governance = SimpleNamespace(
            resource_pipeline=SimpleNamespace(
                provider=kwargs["provider"],
                resource_type=kwargs["resource_type"],
                resource_id=kwargs["resource_id"],
            ),
            decision=SimpleNamespace(
                recommendation=SimpleNamespace(value="proceed"),
                confidence=0.9,
                risk=SimpleNamespace(value="low"),
                preventive=False,
                requires_human_review=False,
                evidence={"decision": "test"},
            ),
            allowed_for_decision=True,
            requires_human_review=False,
            blocked=False,
            evidence={
                "decision_evaluated": True,
                "decision_recommendation": "proceed",
            },
        )

        lifecycle = None
        if self.outcome == "completed":
            lifecycle = SimpleNamespace(
                outcome="completed",
                completed=True,
                blocked=False,
                requires_human_approval=False,
                evidence={"verified": True},
            )

        return SimpleNamespace(
            governance=governance,
            lifecycle=lifecycle,
            outcome=self.outcome,
            execution_started=self.outcome == "completed",
            blocked=self.outcome == "blocked",
            requires_human_review=self.outcome == "review",
            completed=self.outcome == "completed",
            evidence={
                "execution_flow": (
                    "stopped_by_governance"
                    if self.outcome == "blocked"
                    else "stopped_for_human_review"
                    if self.outcome == "review"
                    else "autonomous_lifecycle"
                ),
                "dry_run": True,
            },
        )


def make_client(fake_runner):
    app = FastAPI()
    app.include_router(api.router)
    api.runner = fake_runner
    return TestClient(app)


def payload(action_id="run-api-1"):
    return {
        "provider": "aws",
        "action_id": action_id,
        "action_type": "review_instance_state",
        "resource_type": "ec2_instance",
        "resource_id": "i-123",
        "reason": "API autonomous run test",
        "risk": "low",
        "requires_approval": True,
        "rollback_available": True,
        "dry_run": True,
    }


def test_allow_starts_lifecycle_and_preserves_evidence():
    fake = FakeRunner("completed")
    client = make_client(fake)

    response = client.post("/autonomy/run", json=payload())

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "completed"
    assert data["execution_started"] is True
    assert data["completed"] is True
    assert data["governance"]["evidence"]["decision_evaluated"] is True
    assert data["evidence"]["execution_flow"] == "autonomous_lifecycle"
    assert len(fake.calls) == 1
    assert fake.calls[0]["dry_run"] is True


def test_deny_stops_before_lifecycle():
    fake = FakeRunner("blocked")
    client = make_client(fake)

    response = client.post("/autonomy/run", json=payload("run-api-deny"))

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "blocked"
    assert data["blocked"] is True
    assert data["execution_started"] is False
    assert data["lifecycle"] is None


def test_review_stops_for_human_review():
    fake = FakeRunner("review")
    client = make_client(fake)

    response = client.post("/autonomy/run", json=payload("run-api-review"))

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "review"
    assert data["requires_human_review"] is True
    assert data["execution_started"] is False


def test_request_maps_action_contract_exactly():
    fake = FakeRunner("completed")
    client = make_client(fake)

    response = client.post("/autonomy/run", json=payload("run-api-action"))

    assert response.status_code == 200
    action = fake.calls[0]["action"]
    assert action.action_id == "run-api-action"
    assert action.action_type == "review_instance_state"
    assert action.target.resource_type == "ec2_instance"
    assert action.target.resource_id == "i-123"
    assert action.reason == "API autonomous run test"
    assert action.status.value == "pending_approval"


def test_approver_and_idempotency_are_forwarded():
    fake = FakeRunner("completed")
    client = make_client(fake)

    body = payload("run-api-forward")
    body.update(
        {
            "approved_by": "operator",
            "idempotency_key": "idem-123",
            "idempotency_seen": False,
            "dry_run": False,
        }
    )

    response = client.post("/autonomy/run", json=body)

    assert response.status_code == 200
    call = fake.calls[0]
    assert call["approved_by"] == "operator"
    assert call["idempotency_key"] == "idem-123"
    assert call["idempotency_seen"] is False
    assert call["dry_run"] is False


def test_empty_action_id_is_rejected():
    client = make_client(FakeRunner("completed"))
    body = payload()
    body["action_id"] = ""

    response = client.post("/autonomy/run", json=body)

    assert response.status_code == 422


def test_empty_resource_id_is_rejected():
    client = make_client(FakeRunner("completed"))
    body = payload()
    body["resource_id"] = ""

    response = client.post("/autonomy/run", json=body)

    assert response.status_code == 422


def test_invalid_risk_is_rejected():
    client = make_client(FakeRunner("completed"))
    body = payload()
    body["risk"] = "unknown"

    response = client.post("/autonomy/run", json=body)

    assert response.status_code == 422


def test_runner_value_error_becomes_bad_request():
    class ErrorRunner(FakeRunner):
        def run(self, **kwargs):
            raise ValueError("resource rejected")

    client = make_client(ErrorRunner("completed"))

    response = client.post("/autonomy/run", json=payload())

    assert response.status_code == 400
    assert response.json()["detail"] == "resource rejected"
