from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_policy import ResourcePolicyDecision


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


def test_allow_decision_has_consistent_governance_evidence():
    result = ResourceGovernanceEngine().inspect(
        Provider(), "ec2", "i-task31"
    )

    assert result.decision == ResourcePolicyDecision.ALLOW
    assert result.allowed_for_decision is True
    assert result.blocked is False
    assert result.requires_human_review is False
    assert result.evidence["policy_decision"] == "allow"
    assert result.evidence["allowed_for_decision"] is True
    assert result.evidence["read_only"] is True
