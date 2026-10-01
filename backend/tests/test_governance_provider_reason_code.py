from autonomy.resource_governance_evidence import reason_codes
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)
from autonomy.resource_observer import ResourceObservation


def test_disallowed_provider_has_stable_reason_code():
    observation = ResourceObservation(
        provider="gcp",
        resource_type="ec2",
        resource_id="vm-task33",
    )

    result = ResourcePolicyEngine(ResourcePolicy()).evaluate(observation)

    assert result.decision == ResourcePolicyDecision.DENY
    assert "provider_not_allowed" in reason_codes(result.reasons)
