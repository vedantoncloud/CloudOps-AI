from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_snapshot import policy_snapshot


def test_policy_snapshot_normalizes_case_and_whitespace():
    policy = ResourcePolicy(
        allowed_providers={" AWS ", "Azure"},
        allowed_resource_types={" EC2 ", "S3"},
        required_metadata={" owner ", "environment"},
    )

    snapshot = policy_snapshot(policy)

    assert snapshot["allowed_providers"] == ["aws", "azure"]
    assert snapshot["allowed_resource_types"] == ["ec2", "s3"]
    assert snapshot["required_metadata"] == ["environment", "owner"]


def test_policy_snapshot_sorts_denied_tag_keys():
    policy = ResourcePolicy(
        denied_tag_values={
            "z-risk": {"high", "critical"},
            "a-environment": {"blocked"},
        }
    )

    snapshot = policy_snapshot(policy)

    assert list(snapshot["denied_tag_values"]) == [
        "a-environment",
        "z-risk",
    ]
    assert snapshot["denied_tag_values"]["z-risk"] == [
        "critical",
        "high",
    ]
