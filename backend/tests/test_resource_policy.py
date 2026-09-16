import pytest

from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)


def make_observation(**overrides):
    values = {
        "provider": "aws",
        "resource_type": "ec2",
        "resource_id": "i-123",
        "read_only": True,
        "data": {
            "state": "running",
            "health": "healthy",
            "tags": {"Environment": "prod"},
            "metadata": {"instance_type": "t3.medium"},
        },
    }
    values.update(overrides)
    return ResourceObservation(**values)


def test_allows_compliant_resource():
    result = ResourcePolicyEngine().evaluate(make_observation())

    assert result.decision == ResourcePolicyDecision.ALLOW
    assert result.evidence["provider_allowed"] is True
    assert result.evidence["resource_type_allowed"] is True
    assert result.evidence["missing_metadata"] == []


def test_denies_unknown_provider():
    result = ResourcePolicyEngine().evaluate(
        make_observation(provider="azure")
    )

    assert result.decision == ResourcePolicyDecision.DENY
    assert result.evidence["provider_allowed"] is False


def test_denies_unsupported_resource_type():
    result = ResourcePolicyEngine().evaluate(
        make_observation(resource_type="lambda")
    )

    assert result.decision == ResourcePolicyDecision.DENY
    assert result.evidence["resource_type_allowed"] is False


def test_denies_non_read_only_observation():
    result = ResourcePolicyEngine().evaluate(
        make_observation(read_only=False)
    )

    assert result.decision == ResourcePolicyDecision.DENY
    assert "not read-only" in result.reasons[0]


def test_missing_metadata_requires_review():
    policy = ResourcePolicy(required_metadata={"instance_type", "owner"})
    result = ResourcePolicyEngine(policy).evaluate(make_observation())

    assert result.decision == ResourcePolicyDecision.REVIEW
    assert result.evidence["missing_metadata"] == ["owner"]


def test_denied_tag_value_blocks_resource():
    policy = ResourcePolicy(
        denied_tag_values={"Environment": {"restricted", "blocked"}}
    )
    result = ResourcePolicyEngine(policy).evaluate(
        make_observation(
            data={
                "state": "running",
                "health": "healthy",
                "tags": {"Environment": "blocked"},
                "metadata": {},
            }
        )
    )

    assert result.decision == ResourcePolicyDecision.DENY
    assert result.evidence["denied_tags"] == {"Environment": "blocked"}


def test_provider_and_resource_type_matching_is_case_insensitive():
    policy = ResourcePolicy(
        allowed_providers={"AWS"},
        allowed_resource_types={"EC2"},
    )
    result = ResourcePolicyEngine(policy).evaluate(
        make_observation(provider="aws", resource_type="ec2")
    )

    assert result.decision == ResourcePolicyDecision.ALLOW


def test_custom_policy_can_allow_s3_only():
    policy = ResourcePolicy(
        allowed_providers={"aws"},
        allowed_resource_types={"s3"},
    )

    result = ResourcePolicyEngine(policy).evaluate(
        make_observation(resource_type="s3")
    )

    assert result.decision == ResourcePolicyDecision.ALLOW


def test_policy_result_contains_resource_identity():
    result = ResourcePolicyEngine().evaluate(make_observation())

    assert result.evidence["provider"] == "aws"
    assert result.evidence["resource_type"] == "ec2"
    assert result.evidence["resource_id"] == "i-123"


def test_policy_result_has_reason_for_success():
    result = ResourcePolicyEngine().evaluate(make_observation())

    assert result.reasons
    assert "satisfies" in result.reasons[0]


@pytest.mark.parametrize(
    "resource_type",
    ["lambda", "rds", "eks"],
)
def test_unsupported_types_are_denied_by_default(resource_type):
    result = ResourcePolicyEngine().evaluate(
        make_observation(resource_type=resource_type)
    )

    assert result.decision == ResourcePolicyDecision.DENY
