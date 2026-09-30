from dataclasses import dataclass

from autonomy.resource_policy import ResourcePolicyDecision, ResourcePolicyResult


@dataclass(frozen=True)
class ResourceGovernanceSummary:
    decision: str
    allowed: bool
    requires_review: bool
    blocked: bool
    reason_count: int


def summarize_policy_result(
    result: ResourcePolicyResult,
) -> ResourceGovernanceSummary:
    return ResourceGovernanceSummary(
        decision=result.decision.value,
        allowed=result.decision == ResourcePolicyDecision.ALLOW,
        requires_review=result.decision == ResourcePolicyDecision.REVIEW,
        blocked=result.decision == ResourcePolicyDecision.DENY,
        reason_count=len(result.reasons),
    )
