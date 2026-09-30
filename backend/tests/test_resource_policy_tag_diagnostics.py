from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_tag_diagnostics import denied_tags


def test_denied_tags_returns_sorted_matches():
    policy = ResourcePolicy(
        denied_tag_values={
            "environment": {"production"},
            "team": {"blocked"},
        }
    )

    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-test",
        data={
            "tags": {
                "team": "blocked",
                "environment": "production",
            }
        },
    )

    assert denied_tags(policy, observation) == {
        "environment": "production",
        "team": "blocked",
    }
