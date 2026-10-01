from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_policy_normalization import normalize_policy


def test_normalize_policy_trims_denied_tag_keys_and_values():
    policy = ResourcePolicy(
        denied_tag_values={
            " environment ": {" production ", " staging "},
            "owner": {" team-a "},
        }
    )

    normalized = normalize_policy(policy)

    assert normalized.denied_tag_values == {
        "environment": {"production", "staging"},
        "owner": {"team-a"},
    }


def test_normalize_policy_does_not_mutate_denied_tag_values():
    original = {
        " environment ": {" production "}
    }
    policy = ResourcePolicy(denied_tag_values=original)

    normalize_policy(policy)

    assert policy.denied_tag_values == original
