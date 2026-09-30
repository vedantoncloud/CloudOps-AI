from autonomy.resource_governance_summary import summarize_policy_result
from autonomy.resource_policy import ResourcePolicyDecision, ResourcePolicyResult


def test_governance_summary_for_allow():
    result = ResourcePolicyResult(
        decision=ResourcePolicyDecision.ALLOW,
        reasons=["ok"],
    )

    summary = summarize_policy_result(result)

    assert summary.allowed is True
    assert summary.blocked is False
    assert summary.requires_review is False
    assert summary.reason_count == 1


def test_governance_summary_for_deny():
    result = ResourcePolicyResult(
        decision=ResourcePolicyDecision.DENY,
        reasons=["blocked"],
    )

    summary = summarize_policy_result(result)

    assert summary.allowed is False
    assert summary.blocked is True
