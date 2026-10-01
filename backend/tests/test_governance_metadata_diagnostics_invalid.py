import pytest

from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_diagnostics import missing_required_metadata


@pytest.mark.parametrize("metadata", [None, [], "invalid", 42])
def test_missing_metadata_handles_non_dictionary_values(metadata):
    policy = ResourcePolicy(
        required_metadata={"owner", "environment"}
    )
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task50",
        data={"metadata": metadata},
    )

    assert missing_required_metadata(policy, observation) == [
        "environment",
        "owner",
    ]
