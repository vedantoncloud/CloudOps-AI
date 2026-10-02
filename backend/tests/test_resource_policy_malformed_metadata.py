import pytest

from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)


@pytest.mark.parametrize(
    "metadata",
    [None, [], "invalid-metadata"],
)
def test_non_dictionary_metadata_requires_review_without_crashing(metadata):
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-malformed-metadata",
        read_only=True,
        data={
            "metadata": metadata,
            "tags": {},
        },
    )
    engine = ResourcePolicyEngine(
        ResourcePolicy(required_metadata={"owner"})
    )

    result = engine.evaluate(observation)

    assert result.decision == ResourcePolicyDecision.REVIEW
    assert result.evidence["missing_metadata"] == ["owner"]
    assert any("owner" in reason for reason in result.reasons)
