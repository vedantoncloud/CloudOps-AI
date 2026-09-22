"""Governance wrapper for observed cloud resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.provider import CloudProvider
from autonomy.resource_observer import ResourceObservation, ResourceObserver
from autonomy.resource_policy import (
    ResourcePolicy,
    ResourcePolicyDecision,
    ResourcePolicyEngine,
    ResourcePolicyResult,
)


@dataclass(frozen=True)
class GovernedResourceObservation:
    """A normalized resource observation plus its governance result."""

    observation: ResourceObservation
    policy: ResourcePolicyResult
    allowed_for_decision: bool
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def decision(self) -> ResourcePolicyDecision:
        return self.policy.decision

    @property
    def blocked(self) -> bool:
        return self.decision == ResourcePolicyDecision.DENY

    @property
    def requires_human_review(self) -> bool:
        return self.decision == ResourcePolicyDecision.REVIEW


class ResourceGovernanceEngine:
    """Combine provider observation and governance policy into one read-only gate."""

    def __init__(
        self,
        observer: ResourceObserver | None = None,
        policy_engine: ResourcePolicyEngine | None = None,
    ) -> None:
        self.observer = observer if observer is not None else ResourceObserver()
        self.policy_engine = (
            policy_engine
            if policy_engine is not None
            else ResourcePolicyEngine(ResourcePolicy())
        )

    def inspect(
        self,
        provider: CloudProvider,
        resource_type: str,
        resource_id: str,
    ) -> GovernedResourceObservation:
        observation = self.observer.observe(
            provider=provider,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        policy = self.policy_engine.evaluate(observation)

        allowed_for_decision = policy.decision == ResourcePolicyDecision.ALLOW

        evidence = {
            "provider": observation.provider,
            "resource_type": observation.resource_type,
            "resource_id": observation.resource_id,
            "policy_decision": policy.decision.value,
            "policy_reasons": list(policy.reasons),
            "allowed_for_decision": allowed_for_decision,
            "read_only": observation.read_only,
        }
        evidence.update(policy.evidence)

        return GovernedResourceObservation(
            observation=observation,
            policy=policy,
            allowed_for_decision=allowed_for_decision,
            evidence=evidence,
        )

    def can_proceed(self, result: GovernedResourceObservation) -> bool:
        return result.allowed_for_decision
