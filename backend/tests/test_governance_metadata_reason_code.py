from autonomy.resource_governance_evidence import reason_codes
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)
from autonomy.resource_observer import ResourceObservation


def test_missing_metadata_has_stable_reason_code():
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task36",
        data={"metadata": {}},
    )

    policy = ResourcePolicy(required_metadata={"owner"})
    result = ResourcePolicyEngine(policy).evaluate(observation)

    assert result.decision == ResourcePolicyDecision.REVIEW
    assert "required_metadata_missing" in reason_codes(result.reasons)
    assert result.evidence["missing_metadata"] == ["owner"]
