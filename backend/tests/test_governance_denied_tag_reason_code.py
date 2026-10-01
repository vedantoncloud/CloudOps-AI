from autonomy.resource_governance_evidence import reason_codes
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)
from autonomy.resource_observer import ResourceObservation


def test_denied_tag_has_stable_reason_code():
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task37",
        data={"tags": {"environment": "restricted"}},
    )

    policy = ResourcePolicy(
        denied_tag_values={"environment": {"restricted"}}
    )

    result = ResourcePolicyEngine(policy).evaluate(observation)

    assert result.decision == ResourcePolicyDecision.DENY
    assert "denied_tag" in reason_codes(result.reasons)
    assert result.evidence["denied_tags"] == {
        "environment": "restricted"
    }
