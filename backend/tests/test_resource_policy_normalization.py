from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_normalization import normalize_policy


def test_normalize_policy_removes_whitespace_and_normalizes_case():
    policy = ResourcePolicy(
        allowed_providers={" AWS "},
        allowed_resource_types={" EC2 "},
        required_metadata={" owner "},
    )

    normalized = normalize_policy(policy)

    assert normalized.allowed_providers == {"aws"}
    assert normalized.allowed_resource_types == {"ec2"}
    assert normalized.required_metadata == {"owner"}
