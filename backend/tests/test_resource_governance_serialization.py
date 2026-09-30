from autonomy.resource_governance_serialization import serialize_governance_summary
from autonomy.resource_governance_summary import ResourceGovernanceSummary


def test_governance_summary_serialization():
    summary = ResourceGovernanceSummary(
        decision="review",
        allowed=False,
        requires_review=True,
        blocked=False,
        reason_count=2,
    )

    assert serialize_governance_summary(summary) == {
        "decision": "review",
        "allowed": False,
        "requires_review": True,
        "blocked": False,
        "reason_count": 2,
    }
