from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)


class StubProvider:
    def __init__(self, name="aws", payload=None):
        self._name = name
        self.payload = payload or {}

    @property
    def provider_name(self):
        return self._name

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": self.provider_name,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            **self.payload,
        }


def test_governance_engine_denies_disallowed_provider():
    engine = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(ResourcePolicy())
    )

    result = engine.inspect(
        provider=StubProvider(name="gcp"),
        resource_type="ec2",
        resource_id="resource-deny-provider",
    )

    assert result.decision == ResourcePolicyDecision.DENY
    assert result.blocked is True
    assert result.allowed_for_decision is False
    assert engine.can_proceed(result) is False
    assert result.evidence["provider"] == "gcp"


def test_governance_engine_requires_human_review_for_missing_metadata():
    engine = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(
            ResourcePolicy(required_metadata={"owner"})
        )
    )

    result = engine.inspect(
        provider=StubProvider(payload={"metadata": {}}),
        resource_type="ec2",
        resource_id="resource-needs-review",
    )

    assert result.decision == ResourcePolicyDecision.REVIEW
    assert result.requires_human_review is True
    assert result.blocked is False
    assert result.allowed_for_decision is False
    assert engine.can_proceed(result) is False
    assert "owner" in result.policy.evidence["missing_metadata"]


def test_governance_engine_allows_compliant_read_only_resource():
    engine = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(ResourcePolicy())
    )

    result = engine.inspect(
        provider=StubProvider(),
        resource_type="ec2",
        resource_id="resource-allowed",
    )

    assert result.decision == ResourcePolicyDecision.ALLOW
    assert result.allowed_for_decision is True
    assert result.blocked is False
    assert result.requires_human_review is False
    assert engine.can_proceed(result) is True
    assert result.observation.read_only is True
