from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from main import app
import autonomy.autonomous_run_api as run_api


def _governance(provider="aws", resource_type="ec2_instance", resource_id="i-e2e"):
    return SimpleNamespace(
        resource_pipeline=SimpleNamespace(
            provider=provider,
            resource_type=resource_type,
            resource_id=resource_id,
        ),
        decision=SimpleNamespace(
            recommendation=SimpleNamespace(value="proceed"),
            confidence=0.91,
            risk=SimpleNamespace(value="low"),
            preventive=False,
            requires_human_review=False,
            evidence={"decision": "e2e"},
        ),
        allowed_for_decision=True,
        requires_human_review=False,
        blocked=False,
        evidence={
            "decision_evaluated": True,
            "decision_recommendation": "proceed",
        },
    )


class FakeRun:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
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
            governance=_governance(
                provider=kwargs["provider"],
                resource_type=kwargs["resource_type"],
                resource_id=kwargs["resource_id"],
            ),
            lifecycle=lifecycle,
            outcome=self.outcome,
            execution_started=self.outcome == "completed",
            blocked=self.outcome == "blocked",
            requires_human_review=self.outcome == "review",
            completed=self.outcome == "completed",
            evidence={
                "dry_run": kwargs["dry_run"],
                "execution_flow": (
                    "autonomous_lifecycle"
                    if self.outcome == "completed"
                    else "stopped_by_governance"
                    if self.outcome == "blocked"
                    else "stopped_for_human_review"
                ),
            },
        )


def _payload():
    return {
        "provider": "aws",
        "action_id": "e2e-action-1",
        "action_type": "review_instance_state",
        "resource_type": "ec2_instance",
        "resource_id": "i-e2e",
        "reason": "E2E autonomous run validation",
        "risk": "low",
        "requires_approval": True,
        "rollback_available": True,
        "dry_run": True,
    }


def test_main_app_exposes_autonomous_run_route():
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/autonomy/run" in paths


def test_main_app_allow_flow_returns_lifecycle_result(monkeypatch):
    fake = FakeRun("completed")
    monkeypatch.setattr(run_api, "runner", fake)

    response = TestClient(app).post("/autonomy/run", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "completed"
    assert data["execution_started"] is True
    assert data["completed"] is True
    assert data["evidence"]["execution_flow"] == "autonomous_lifecycle"
    assert data["governance"]["evidence"]["decision_evaluated"] is True
    assert fake.calls[0]["dry_run"] is True


def test_main_app_deny_flow_does_not_start_execution(monkeypatch):
    fake = FakeRun("blocked")
    monkeypatch.setattr(run_api, "runner", fake)

    response = TestClient(app).post("/autonomy/run", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "blocked"
    assert data["blocked"] is True
    assert data["execution_started"] is False
    assert data["lifecycle"] is None


def test_main_app_review_flow_requires_human_review(monkeypatch):
    fake = FakeRun("review")
    monkeypatch.setattr(run_api, "runner", fake)

    response = TestClient(app).post("/autonomy/run", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "review"
    assert data["requires_human_review"] is True
    assert data["execution_started"] is False


def test_main_app_forwards_approval_and_idempotency(monkeypatch):
    fake = FakeRun("completed")
    monkeypatch.setattr(run_api, "runner", fake)

    body = _payload()
    body.update(
        {
            "approved_by": "operator",
            "idempotency_key": "e2e-idem-1",
            "idempotency_seen": False,
        }
    )

    response = TestClient(app).post("/autonomy/run", json=body)

    assert response.status_code == 200
    call = fake.calls[0]
    assert call["approved_by"] == "operator"
    assert call["idempotency_key"] == "e2e-idem-1"
    assert call["idempotency_seen"] is False


def test_main_app_rejects_invalid_request_before_runner(monkeypatch):
    fake = FakeRun("completed")
    monkeypatch.setattr(run_api, "runner", fake)

    body = _payload()
    body["resource_id"] = ""

    response = TestClient(app).post("/autonomy/run", json=body)

    assert response.status_code == 422
    assert fake.calls == []
