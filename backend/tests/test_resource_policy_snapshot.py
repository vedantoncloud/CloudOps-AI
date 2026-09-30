from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_snapshot import policy_snapshot


def test_policy_snapshot_is_deterministic():
    policy = ResourcePolicy(
        allowed_providers={"s3", "aws"},
        allowed_resource_types={"s3", "ec2"},
        required_metadata={"owner", "environment"},
    )

    assert policy_snapshot(policy) == {
        "allowed_providers": ["aws", "s3"],
        "allowed_resource_types": ["ec2", "s3"],
        "require_read_only": True,
        "required_metadata": ["environment", "owner"],
        "denied_tag_values": {},
    }
