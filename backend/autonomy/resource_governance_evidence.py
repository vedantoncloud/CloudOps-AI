from autonomy.resource_governance_summary import summarize_policy_result
from autonomy.resource_policy import ResourcePolicyResult
from autonomy.resource_policy_snapshot import policy_snapshot
from autonomy.resource_policy import ResourcePolicy


def build_governance_evidence(
    policy: ResourcePolicy,
    result: ResourcePolicyResult,
) -> dict:
    summary = summarize_policy_result(result)

    return {
        "policy": policy_snapshot(policy),
        "decision": summary.decision,
        "allowed": summary.allowed,
        "blocked": summary.blocked,
        "requires_review": summary.requires_review,
        "reason_count": summary.reason_count,
        "reasons": list(result.reasons),
        "policy_evidence": dict(result.evidence),
    }
