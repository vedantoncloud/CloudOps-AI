from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware
from autonomy.audit import AuditTrail
import autonomy.autonomous_run_api as api
from autonomy.persistent_audit_trail import PersistentAuditTrail


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
    app.add_middleware(AccessControlMiddleware, mode="development", tokens={})
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
    assert fake.calls[0]["actor_id"] == "local-development"


def test_default_run_lifecycle_uses_durable_shared_audit_trail(tmp_path, monkeypatch):
    trail = PersistentAuditTrail(tmp_path / "run-audit.db")
    monkeypatch.setattr(api, "audit_trail", trail)
    runner = api._create_runner()

    action = api._action(api.AutonomousRunRequest(**payload("durable-run")))
    runner.lifecycle._audit(
        action,
        old_status="pending_approval",
        new_status="pending_approval",
        event="autonomous_lifecycle_started",
        details={"dry_run": True},
        actor_id="operator-7",
    )

    reopened = PersistentAuditTrail(tmp_path / "run-audit.db")
    events = reopened.get_events(action_id="durable-run")
    assert len(events) == 1
    assert events[0].event == "autonomous_lifecycle_started"
    assert events[0].actor_id == "operator-7"
    assert reopened.verify_integrity()


def test_run_history_groups_events_and_only_returns_current_actors_runs(monkeypatch):
    trail = AuditTrail()
    monkeypatch.setattr(api, "audit_trail", trail)
    for action_id, actor, event, status in (
        ("owned-older", "local-development", "autonomous_lifecycle_started", "pending_approval"),
        ("owned", "local-development", "autonomous_lifecycle_started", "pending_approval"),
        ("owned", "local-development", "autonomous_lifecycle_completed", "completed"),
        ("foreign", "another-operator", "autonomous_lifecycle_completed", "completed"),
    ):
        trail.record(
            action_id=action_id,
            action_type="review_instance_state",
            resource_type="ec2_instance",
            resource_id="i-123",
            old_status="pending_approval",
            new_status=status,
            event=event,
            details={"dry_run": True},
            actor_id=actor,
        )

    client = make_client(FakeRunner("completed"))
    response = client.get("/autonomy/runs?limit=1")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["runs"]) == 1
    assert data["runs"][0]["action_id"] == "owned"
    assert data["runs"][0]["outcome"] == "completed"
    assert data["runs"][0]["status"] == "completed"
    assert data["runs"][0]["dry_run"] is True
    assert client.get("/autonomy/runs?offset=1").json()["runs"][0]["action_id"] == "owned-older"

    details = client.get("/autonomy/runs/owned")
    assert details.status_code == 200
    assert [event["event"] for event in details.json()["events"]] == [
        "autonomous_lifecycle_started",
        "autonomous_lifecycle_completed",
    ]
    assert details.json()["events"][0]["details"] == {"dry_run": True}
    assert client.get("/autonomy/runs/foreign").status_code == 404
    assert client.get("/autonomy/runs/missing").status_code == 404


def test_run_history_paginates_and_validates_bounds(monkeypatch):
    monkeypatch.setattr(api, "audit_trail", AuditTrail())
    client = make_client(FakeRunner("completed"))

    assert client.get("/autonomy/runs?limit=0").status_code == 422
    assert client.get("/autonomy/runs?offset=-1").status_code == 422


def test_run_history_filters_outcome_and_search_before_pagination(monkeypatch):
    trail = AuditTrail()
    monkeypatch.setattr(api, "audit_trail", trail)
    entries = (
        ("completed-ec2", "autonomous_lifecycle_completed", "completed", "i-123", "resize_instance"),
        ("blocked-s3", "autonomous_lifecycle_blocked", "blocked", "bucket-prod", "delete_object"),
        ("waiting-ec2", "autonomous_lifecycle_waiting", "pending_approval", "i-456", "stop_instance"),
        ("foreign-match", "autonomous_lifecycle_blocked", "blocked", "i-789", "resize_instance"),
    )
    for action_id, event, status, resource_id, action_type in entries:
        trail.record(
            action_id=action_id,
            action_type=action_type,
            resource_type="ec2_instance" if resource_id.startswith("i-") else "s3_bucket",
            resource_id=resource_id,
            old_status="pending_approval",
            new_status=status,
            event=event,
            details={},
            actor_id="another-operator" if action_id == "foreign-match" else "local-development",
        )

    client = make_client(FakeRunner("completed"))
    response = client.get("/autonomy/runs?outcome=blocked&search=BUCKET&limit=1")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [run["action_id"] for run in data["runs"]] == ["blocked-s3"]
    assert data["runs"][0]["outcome"] == "blocked"
    assert client.get("/autonomy/runs?outcome=unknown").status_code == 422
    assert client.get("/autonomy/runs?search=" + "x" * 201).status_code == 422


def test_run_history_filters_updated_time_before_pagination(monkeypatch):
    events = [
        SimpleNamespace(
            action_id=action_id, actor_id="local-development", event=event,
            action_type="resize_instance", resource_type="ec2_instance", resource_id="i-123",
            old_status="pending_approval", new_status="completed", timestamp=timestamp,
            details={},
        )
        for action_id, event, timestamp in (
            ("run-before", "autonomous_lifecycle_completed", "2026-01-01T00:00:00+00:00"),
            ("run-in-window", "autonomous_lifecycle_completed", "2026-01-02T12:00:00+00:00"),
            ("run-after", "autonomous_lifecycle_blocked", "2026-01-04T00:00:00+00:00"),
        )
    ]
    monkeypatch.setattr(api, "audit_trail", SimpleNamespace(get_events=lambda: events))

    client = make_client(FakeRunner("completed"))
    response = client.get(
        "/autonomy/runs?start_time=2026-01-02T12:00:00Z&end_time=2026-01-03T00:00:00Z&limit=1"
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [run["action_id"] for run in response.json()["runs"]] == ["run-in-window"]
    assert client.get(
        "/autonomy/runs?start_time=2026-01-03T00:00:00Z&end_time=2026-01-02T00:00:00Z"
    ).status_code == 422
    assert client.get("/autonomy/runs?start_time=not-a-date").status_code == 422


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
