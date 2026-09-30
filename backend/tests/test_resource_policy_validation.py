from autonomy.resource_policy import ResourcePolicy


def test_default_resource_policy_is_valid():
    policy = ResourcePolicy()

    assert "aws" in policy.allowed_providers
    assert "ec2" in policy.allowed_resource_types
    assert "s3" in policy.allowed_resource_types
    assert policy.require_read_only is True
