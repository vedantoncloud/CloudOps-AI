from autonomy.resource_governance_evidence import reason_codes
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)
from autonomy.resource_observer import ResourceObservation


def test_mutable_observation_is_denied_with_reason_code():
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task35",
        read_only=False,
    )

    result = ResourcePolicyEngine(ResourcePolicy()).evaluate(observation)

    assert result.decision == ResourcePolicyDecision.DENY
    assert "read_only_required" in reason_codes(result.reasons)
    assert result.evidence["read_only"] is False
