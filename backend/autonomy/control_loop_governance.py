from dataclasses import dataclass, field
from typing import Any

from autonomy.provider import CloudProvider
from autonomy.resource_governance import (
    GovernedResourceObservation,
    ResourceGovernanceEngine,
)
from autonomy.resource_policy import ResourcePolicyDecision


@dataclass(frozen=True)
class GovernanceGateResult:
    """Control-loop gate result produced before decision/action execution."""

    allowed: bool
    requires_human_review: bool
    blocked: bool
    decision: ResourcePolicyDecision
    resource: GovernedResourceObservation
    evidence: dict[str, Any] = field(default_factory=dict)


class ControlLoopGovernanceGate:
    """Apply resource governance as a deterministic control-loop safety gate."""

    def __init__(
        self,
        governance: ResourceGovernanceEngine | None = None,
    ) -> None:
        self.governance = (
            governance
            if governance is not None
            else ResourceGovernanceEngine()
        )

    def evaluate(
        self,
        provider: CloudProvider,
        resource_type: str,
        resource_id: str,
    ) -> GovernanceGateResult:
        resource = self.governance.inspect(
            provider=provider,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        decision = resource.policy.decision
        allowed = decision == ResourcePolicyDecision.ALLOW
        requires_human_review = decision == ResourcePolicyDecision.REVIEW
        blocked = decision == ResourcePolicyDecision.DENY

        evidence = dict(resource.evidence)
        evidence.update(
            {
                "governance_gate": "allow" if allowed else (
                    "review" if requires_human_review else "deny"
                ),
                "action_execution_allowed": False,
            }
        )

        return GovernanceGateResult(
            allowed=allowed,
            requires_human_review=requires_human_review,
            blocked=blocked,
            decision=decision,
            resource=resource,
            evidence=evidence,
        )
