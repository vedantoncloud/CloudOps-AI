from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)


class Provider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "metadata": {},
            "tags": {},
        }


def test_review_decision_requires_human_approval():
    engine = ResourceGovernanceEngine(
        policy_engine=ResourcePolicyEngine(
            ResourcePolicy(required_metadata={"owner"})
        )
    )

    result = engine.inspect(Provider(), "ec2", "i-task32")

    assert result.decision == ResourcePolicyDecision.REVIEW
    assert result.requires_human_review is True
    assert result.allowed_for_decision is False
    assert result.blocked is False
    assert engine.can_proceed(result) is False
    assert "owner" in result.policy.evidence["missing_metadata"]
