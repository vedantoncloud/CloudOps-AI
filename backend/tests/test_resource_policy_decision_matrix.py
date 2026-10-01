import pytest

from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
)


@pytest.mark.parametrize(
    ("observation", "policy", "expected"),
    [
        (
            ResourceObservation("aws", "ec2", "i-allow"),
            ResourcePolicy(),
            ResourcePolicyDecision.ALLOW,
        ),
        (
            ResourceObservation("gcp", "ec2", "vm-deny"),
            ResourcePolicy(),
            ResourcePolicyDecision.DENY,
        ),
        (
            ResourceObservation("aws", "rds", "db-deny"),
            ResourcePolicy(),
            ResourcePolicyDecision.DENY,
        ),
        (
            ResourceObservation("aws", "ec2", "i-review"),
            ResourcePolicy(required_metadata={"owner"}),
            ResourcePolicyDecision.REVIEW,
        ),
        (
            ResourceObservation(
                "aws",
                "ec2",
                "i-tag-deny",
                data={"tags": {"environment": "restricted"}},
            ),
            ResourcePolicy(
                denied_tag_values={"environment": {"restricted"}}
            ),
            ResourcePolicyDecision.DENY,
        ),
        (
            ResourceObservation(
                "aws",
                "ec2",
                "i-not-readonly",
                read_only=False,
            ),
            ResourcePolicy(),
            ResourcePolicyDecision.DENY,
        ),
    ],
)
def test_resource_policy_decision_matrix(observation, policy, expected):
    result = ResourcePolicyEngine(policy).evaluate(observation)

    assert result.decision == expected
    assert result.reasons
    assert result.evidence["provider"] == observation.provider
    assert result.evidence["resource_type"] == observation.resource_type
    assert result.evidence["resource_id"] == observation.resource_id


def test_policy_review_records_missing_required_metadata():
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-owner-review",
        data={"metadata": {}},
    )

    result = ResourcePolicyEngine(
        ResourcePolicy(required_metadata={"owner", "team"})
    ).evaluate(observation)

    assert result.decision == ResourcePolicyDecision.REVIEW
    assert result.evidence["missing_metadata"] == ["owner", "team"]
