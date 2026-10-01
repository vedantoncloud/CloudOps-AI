from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_tag_diagnostics import denied_tags


def test_denied_tags_returns_sorted_matching_tags():
    policy = ResourcePolicy(
        denied_tag_values={
            "z-risk": {"critical"},
            "a-environment": {"blocked"},
            "owner": {"unknown"},
        }
    )
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task51",
        data={
            "tags": {
                "z-risk": "critical",
                "a-environment": "blocked",
                "owner": "platform",
            }
        },
    )

    assert denied_tags(policy, observation) == {
        "a-environment": "blocked",
        "z-risk": "critical",
    }


def test_denied_tags_returns_empty_when_no_values_match():
    policy = ResourcePolicy(
        denied_tag_values={"environment": {"blocked"}}
    )
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-task51",
        data={"tags": {"environment": "development"}},
    )

    assert denied_tags(policy, observation) == {}
