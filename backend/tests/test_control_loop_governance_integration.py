from dataclasses import dataclass

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.control_loop_api import governance_gate, provider_registry, router
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyDecision, ResourcePolicyEngine
from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.control_loop_governance import ControlLoopGovernanceGate


@dataclass
class FakeProvider:
    provider_name: str = "aws"

    def get_resource(self, resource_type: str, resource_id: str):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "state": "running",
            "health": "healthy",
            "tags": {"Environment": "prod"},
            "metadata": {"instance_type": "t3.medium"},
        }




@pytest.fixture(autouse=True)
def reset_governance_gate():
    original_governance = governance_gate.governance
    yield
    governance_gate.governance = original_governance

def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def payload(action_id="governance-api-1"):
    return {
        "provider": "aws",
        "action_id": action_id,
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-governed-1",
        "reason": "High CPU utilization detected",
        "risk": "medium",
        "requires_approval": True,
        "field": "instance_type",
        "desired_value": "t3.large",
        "current_value": "t3.medium",
    }


def test_control_loop_allows_compliant_resource_and_carries_governance_evidence():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")
    provider_registry.register(FakeProvider())

    response = client().post("/autonomy/control-loop/evaluate", json=payload())

    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is False
    assert body["evidence"]["governance"]["policy_decision"] == "allow"
    assert body["evidence"]["governance"]["allowed_for_decision"] is True


def test_control_loop_review_gate_stops_before_decision_engine():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")
    provider_registry.register(FakeProvider())

    governance_gate.governance = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(ResourcePolicy(required_metadata={"owner"}))
    )

    response = client().post("/autonomy/control-loop/evaluate", json=payload("review-api-1"))

    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"] == "review"
    assert body["requires_human_review"] is True
    assert body["blocked"] is False
    assert body["gitops_created"] is False


def test_control_loop_deny_gate_blocks_action_and_gitops():
    if provider_registry.has("aws"):
        provider_registry.unregister("aws")
    provider_registry.register(FakeProvider())

    governance_gate.governance = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(ResourcePolicy(allowed_resource_types={"s3"}))
    )

    response = client().post("/autonomy/control-loop/evaluate", json=payload("deny-api-1"))

    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"] == "deny"
    assert body["blocked"] is True
    assert body["gitops_created"] is False
    assert body["evidence"]["governance"]["policy_decision"] == "deny"


def test_governance_is_evaluated_before_normal_decision_flow():
    assert isinstance(governance_gate, ControlLoopGovernanceGate)
