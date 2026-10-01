from autonomy.resource_governance_summary import summarize_policy_result
from autonomy.resource_policy import ResourcePolicyDecision, ResourcePolicyResult


def test_governance_summary_for_review():
    result = ResourcePolicyResult(
        decision=ResourcePolicyDecision.REVIEW,
        reasons=["Required resource metadata is missing."],
    )

    summary = summarize_policy_result(result)

    assert summary.decision == "review"
    assert summary.allowed is False
    assert summary.requires_review is True
    assert summary.blocked is False
    assert summary.reason_count == 1


def test_governance_summary_counts_multiple_reasons():
    result = ResourcePolicyResult(
        decision=ResourcePolicyDecision.DENY,
        reasons=["reason-a", "reason-b", "reason-c"],
    )

    summary = summarize_policy_result(result)

    assert summary.reason_count == 3
    assert summary.blocked is True
