from dataclasses import dataclass

import pytest

from autonomy.resource_governance import (
    GovernedResourceObservation,
    ResourceGovernanceEngine,
)
from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)


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


def test_inspect_combines_observation_and_policy():
    result = ResourceGovernanceEngine().inspect(
        FakeProvider(), "ec2", "i-123"
    )

    assert isinstance(result, GovernedResourceObservation)
    assert result.observation.resource_id == "i-123"
    assert result.policy.decision == ResourcePolicyDecision.ALLOW
    assert result.allowed_for_decision is True


def test_can_proceed_matches_governance_gate():
    engine = ResourceGovernanceEngine()
    result = engine.inspect(FakeProvider(), "ec2", "i-123")

    assert engine.can_proceed(result) is True


def test_denied_resource_cannot_proceed():
    policy = ResourcePolicy(
        allowed_providers={"aws"},
        allowed_resource_types={"s3"},
    )
    engine = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(policy)
    )

    result = engine.inspect(FakeProvider(), "ec2", "i-123")

    assert result.policy.decision == ResourcePolicyDecision.DENY
    assert result.allowed_for_decision is False
    assert engine.can_proceed(result) is False


def test_review_resource_cannot_proceed_automatically():
    policy = ResourcePolicy(required_metadata={"owner"})
    engine = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(policy)
    )

    result = engine.inspect(FakeProvider(), "ec2", "i-123")

    assert result.policy.decision == ResourcePolicyDecision.REVIEW
    assert result.allowed_for_decision is False


def test_governance_evidence_contains_policy_context():
    result = ResourceGovernanceEngine().inspect(
        FakeProvider(), "ec2", "i-123"
    )

    assert result.evidence["provider"] == "aws"
    assert result.evidence["resource_type"] == "ec2"
    assert result.evidence["resource_id"] == "i-123"
    assert result.evidence["policy_decision"] == "allow"
    assert result.evidence["allowed_for_decision"] is True
    assert result.evidence["read_only"] is True


def test_observer_errors_are_not_hidden():
    class BrokenProvider:
        provider_name = "aws"

    with pytest.raises(ValueError, match="does not support resource observation"):
        ResourceGovernanceEngine().inspect(
            BrokenProvider(), "ec2", "i-123"
        )


def test_custom_observer_can_be_injected():
    class StubObserver:
        def observe(self, provider, resource_type, resource_id):
            return ResourceObservation(
                provider=provider.provider_name,
                resource_type=resource_type,
                resource_id=resource_id,
                data={
                    "state": "running",
                    "health": "healthy",
                    "tags": {},
                    "metadata": {},
                },
            )

    result = ResourceGovernanceEngine(
        observer=StubObserver()
    ).inspect(FakeProvider(), "ec2", "i-123")

    assert result.observation.resource_id == "i-123"
    assert result.policy.decision == ResourcePolicyDecision.ALLOW


def test_custom_policy_engine_can_be_injected():
    class AlwaysReview:
        def evaluate(self, observation):
            from autonomy.resource_policy import ResourcePolicyResult
            return ResourcePolicyResult(
                decision=ResourcePolicyDecision.REVIEW,
                reasons=["manual review required"],
                evidence={"custom": True},
            )

    result = ResourceGovernanceEngine(
        policy_engine=AlwaysReview()
    ).inspect(FakeProvider(), "ec2", "i-123")

    assert result.policy.decision == ResourcePolicyDecision.REVIEW
    assert result.allowed_for_decision is False
    assert result.evidence["custom"] is True


def test_governance_remains_read_only():
    provider = FakeProvider()
    result = ResourceGovernanceEngine().inspect(
        provider, "ec2", "i-123"
    )

    assert result.observation.read_only is True
    assert not hasattr(provider, "update_resource")


def test_governance_result_preserves_normalized_data():
    result = ResourceGovernanceEngine().inspect(
        FakeProvider(), "ec2", "i-123"
    )

    assert result.observation.data["state"] == "running"
    assert result.observation.data["health"] == "healthy"
    assert result.observation.data["tags"] == {"Environment": "prod"}
    assert result.observation.data["metadata"]["instance_type"] == "t3.medium"


def test_deny_takes_precedence_over_missing_metadata_review():
    policy = ResourcePolicy(
        allowed_resource_types={"s3"},
        required_metadata={"owner"},
    )
    engine = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(policy)
    )

    result = engine.inspect(FakeProvider(), "ec2", "i-123")

    assert result.policy.decision == ResourcePolicyDecision.DENY
    assert result.allowed_for_decision is False
