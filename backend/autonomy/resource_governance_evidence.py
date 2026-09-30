from autonomy.resource_governance_summary import summarize_policy_result
from autonomy.resource_policy import ResourcePolicyResult
from autonomy.resource_policy_snapshot import policy_snapshot
from autonomy.resource_policy_reasons import ResourcePolicyReason
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


def reason_codes(reasons: list[str]) -> list[str]:
    """Map human-readable policy reasons to stable machine-readable codes."""
    codes = []

    for reason in reasons:
        lowered = reason.lower()

        if "provider" in lowered and "not allowed" in lowered:
            codes.append(ResourcePolicyReason.PROVIDER_NOT_ALLOWED.value)
        elif "resource type" in lowered and "not allowed" in lowered:
            codes.append(ResourcePolicyReason.RESOURCE_TYPE_NOT_ALLOWED.value)
        elif "not read-only" in lowered:
            codes.append(ResourcePolicyReason.READ_ONLY_REQUIRED.value)
        elif "metadata" in lowered and "missing" in lowered:
            codes.append(ResourcePolicyReason.REQUIRED_METADATA_MISSING.value)
        elif "denied tag" in lowered:
            codes.append(ResourcePolicyReason.DENIED_TAG.value)

    return sorted(set(codes))
