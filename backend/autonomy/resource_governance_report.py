from autonomy.resource_governance import GovernedResourceObservation
from autonomy.resource_governance_evidence import build_governance_evidence
from autonomy.resource_policy import ResourcePolicy


def build_resource_governance_report(
    governed: GovernedResourceObservation,
    policy: ResourcePolicy,
) -> dict:
    evidence = build_governance_evidence(policy, governed.policy)

    return {
        "provider": governed.observation.provider,
        "resource_type": governed.observation.resource_type,
        "resource_id": governed.observation.resource_id,
        "read_only": governed.observation.read_only,
        "decision": governed.decision.value,
        "allowed_for_decision": governed.allowed_for_decision,
        "blocked": governed.blocked,
        "requires_human_review": governed.requires_human_review,
        "evidence": evidence,
    }
