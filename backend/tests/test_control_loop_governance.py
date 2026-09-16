from dataclasses import dataclass

from autonomy.control_loop_governance import (
    ControlLoopGovernanceGate,
    GovernanceGateResult,
)
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyDecision, ResourcePolicyEngine
from autonomy.resource_governance import ResourceGovernanceEngine


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


def test_allow_gate_allows_decision_but_not_direct_execution():
    result = ControlLoopGovernanceGate().evaluate(
        FakeProvider(), "ec2", "i-001"
    )

    assert isinstance(result, GovernanceGateResult)
    assert result.decision == ResourcePolicyDecision.ALLOW
    assert result.allowed is True
    assert result.requires_human_review is False
    assert result.blocked is False
    assert result.evidence["action_execution_allowed"] is False


def test_review_gate_requires_human_review():
    policy = ResourcePolicy(required_metadata={"owner"})
    engine = ControlLoopGovernanceGate(
        ResourceGovernanceEngine(
            policy_engine=ResourcePolicyEngine(policy)
        )
    )

    result = engine.evaluate(FakeProvider(), "ec2", "i-001")

    assert result.decision == ResourcePolicyDecision.REVIEW
    assert result.allowed is False
    assert result.requires_human_review is True
    assert result.blocked is False
    assert result.evidence["governance_gate"] == "review"


def test_deny_gate_blocks_progression():
    policy = ResourcePolicy(allowed_resource_types={"s3"})
    engine = ControlLoopGovernanceGate(
        ResourceGovernanceEngine(
            policy_engine=ResourcePolicyEngine(policy)
        )
    )

    result = engine.evaluate(FakeProvider(), "ec2", "i-001")

    assert result.decision == ResourcePolicyDecision.DENY
    assert result.allowed is False
    assert result.requires_human_review is False
    assert result.blocked is True
    assert result.evidence["governance_gate"] == "deny"


def test_governance_evidence_is_preserved():
    result = ControlLoopGovernanceGate().evaluate(
        FakeProvider(), "ec2", "i-001"
    )

    assert result.evidence["provider"] == "aws"
    assert result.evidence["resource_id"] == "i-001"
    assert result.evidence["policy_decision"] == "allow"
    assert result.evidence["allowed_for_decision"] is True


def test_gate_is_read_only():
    result = ControlLoopGovernanceGate().evaluate(
        FakeProvider(), "ec2", "i-001"
    )

    assert result.resource.observation.read_only is True
    assert result.evidence["action_execution_allowed"] is False


def test_gate_preserves_resource_observation():
    result = ControlLoopGovernanceGate().evaluate(
        FakeProvider(), "ec2", "i-001"
    )

    assert result.resource.observation.data["state"] == "running"
    assert result.resource.observation.data["tags"] == {"Environment": "prod"}
    assert result.resource.observation.data["metadata"]["instance_type"] == "t3.medium"


def test_custom_governance_engine_is_reused():
    governance = ResourceGovernanceEngine()
    gate = ControlLoopGovernanceGate(governance)

    first = gate.evaluate(FakeProvider(), "ec2", "i-001")
    second = gate.evaluate(FakeProvider(), "ec2", "i-002")

    assert first.allowed is True
    assert second.allowed is True
    assert second.resource.observation.resource_id == "i-002"
