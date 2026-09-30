from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_diagnostics import missing_required_metadata


def test_missing_required_metadata_is_sorted():
    policy = ResourcePolicy(
        required_metadata={"owner", "environment", "team"}
    )

    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-test",
        data={"metadata": {"owner": "vedant"}},
    )

    assert missing_required_metadata(policy, observation) == [
        "environment",
        "team",
    ]
