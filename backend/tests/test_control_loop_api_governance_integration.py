from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.control_loop_api as api
from autonomy.audit import AuditTrail
from autonomy.control_loop_governance import ControlLoopGovernanceGate
from autonomy.resource_context_pipeline import ResourceContextPipeline
from autonomy.resource_discovery import ResourceDiscovery
from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyEngine


def make_app():
    app = FastAPI()
    app.include_router(api.router)
    return app


def make_payload(action_id):
    return {
        "action_id": action_id,
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-governance-api-123",
        "reason": "High CPU utilization detected",
        "risk": "medium",
        "requires_approval": True,
        "field": "instance_type",
        "desired_value": "t3.large",
        "current_value": "t3.medium",
    }


def configure_governance(monkeypatch, policy):
    gate = ControlLoopGovernanceGate(
        ResourceGovernanceEngine(
            policy_engine=ResourcePolicyEngine(policy)
        )
    )
    pipeline = ResourceContextPipeline(
        discovery=ResourceDiscovery(api.provider_registry),
        governance_gate=gate,
    )
    trail = AuditTrail()
    monkeypatch.setattr(api, "resource_context_pipeline", pipeline)
    monkeypatch.setattr(api, "audit_trail", trail)
    return trail


def test_api_deny_governance_blocks_progression_and_preserves_audit(monkeypatch):
    trail = configure_governance(
        monkeypatch,
        ResourcePolicy(allowed_resource_types={"s3"}),
    )
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload("governance-deny-api"),
    )

    assert response.status_code == 200
    data = response.json()

    assert data["recommendation"] == "deny"
    assert data["blocked"] is True
    assert data["gitops_created"] is False
    assert data["gitops_change_id"] is None
    assert data["gitops_status"] is None
    assert data["evidence"]["governance"]["policy_decision"] == "deny"
    assert data["evidence"]["governance"]["allowed_for_decision"] is False
    assert data["evidence"]["governance"]["action_execution_allowed"] is False

    events = trail.get_events(action_id="governance-deny-api")
    event_names = [event.event for event in events]

    assert "control_loop_governance_blocked" in event_names
    assert "control_loop_blocked" in event_names

    legacy = next(
        event for event in events
        if event.event == "control_loop_blocked"
    )
    assert legacy.action_type == "control_loop_blocked"
    assert legacy.old_status == "pending"
    assert legacy.new_status == "blocked"
    assert legacy.details["blocked"] is True
    assert legacy.details["policy_decision"] == "deny"
    assert legacy.details["evidence"]["action_execution_allowed"] is False


def test_api_review_governance_requires_review_without_gitops(monkeypatch):
    trail = configure_governance(
        monkeypatch,
        ResourcePolicy(required_metadata={"owner"}),
    )
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload("governance-review-api"),
    )

    assert response.status_code == 200
    data = response.json()

    assert data["recommendation"] == "review"
    assert data["blocked"] is False
    assert data["requires_human_review"] is True
    assert data["gitops_created"] is False
    assert data["evidence"]["governance"]["policy_decision"] == "review"
    assert data["evidence"]["governance"]["allowed_for_decision"] is False
    assert data["evidence"]["governance"]["action_execution_allowed"] is False

    events = trail.get_events(action_id="governance-review-api")
    assert any(
        event.event == "control_loop_governance_review"
        for event in events
    )
    assert not any(
        event.event == "control_loop_blocked"
        for event in events
    )


def test_api_allow_governance_evidence_reaches_response_and_audit(monkeypatch):
    trail = configure_governance(monkeypatch, ResourcePolicy())
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json=make_payload("governance-allow-api"),
    )

    assert response.status_code == 200
    data = response.json()

    assert data["blocked"] is False
    assert data["evidence"]["governance"]["policy_decision"] == "allow"
    assert data["evidence"]["governance"]["allowed_for_decision"] is True
    assert data["evidence"]["governance"]["action_execution_allowed"] is False
    assert data["gitops_created"] is True
    assert data["gitops_status"] == "pending_approval"

    events = trail.get_events(action_id="governance-allow-api")
    assert any(
        event.event == "control_loop_evaluated"
        and event.details["governance"]["policy_decision"] == "allow"
        and event.details["governance"]["action_execution_allowed"] is False
        for event in events
    )
    assert not any(
        event.event == "control_loop_blocked"
        for event in events
    )
