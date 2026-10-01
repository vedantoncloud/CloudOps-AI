from autonomy.resource_governance_evidence import reason_codes
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)
from autonomy.resource_observer import ResourceObservation


def test_unsupported_type_has_stable_reason_code():
    observation = ResourceObservation(
        provider="aws",
        resource_type="rds",
        resource_id="db-task34",
    )

    result = ResourcePolicyEngine(ResourcePolicy()).evaluate(observation)

    assert result.decision == ResourcePolicyDecision.DENY
    assert "resource_type_not_allowed" in reason_codes(result.reasons)
