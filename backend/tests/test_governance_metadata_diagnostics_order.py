from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_diagnostics import missing_required_metadata


def test_missing_metadata_is_sorted_deterministically():
    policy = ResourcePolicy(
        required_metadata={"owner", "environment", "team"}
    )
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task49",
        data={"metadata": {"owner": "platform"}},
    )

    assert missing_required_metadata(policy, observation) == [
        "environment",
        "team",
    ]


def test_missing_metadata_returns_empty_when_all_keys_exist():
    policy = ResourcePolicy(
        required_metadata={"owner", "environment"}
    )
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task49",
        data={
            "metadata": {
                "owner": "platform",
                "environment": "test",
            }
        },
    )

    assert missing_required_metadata(policy, observation) == []
