from dataclasses import dataclass, field
from typing import Any

from autonomy.control_loop_governance import (
    ControlLoopGovernanceGate,
    GovernanceGateResult,
)
from autonomy.decision_intelligence import ResourceContext
from autonomy.provider import CloudProvider
from autonomy.resource_discovery import ResourceDiscovery


@dataclass(frozen=True)
class ResourceContextPipelineResult:
    """Unified resource discovery, observation, and governance result."""

    provider: str
    resource_type: str
    resource_id: str
    resource_context: ResourceContext
    governance: GovernanceGateResult
    discovered: bool
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed_for_decision(self) -> bool:
        return self.governance.allowed

    @property
    def requires_human_review(self) -> bool:
        return self.governance.requires_human_review

    @property
    def blocked(self) -> bool:
        return self.governance.blocked


class ResourceContextPipeline:
    """Build a governed ResourceContext for the control loop.

    Discovery establishes whether the resource is present in the provider
    inventory. The governance gate remains authoritative for whether the
    resource may proceed to Decision Intelligence.
    """

    def __init__(
        self,
        *,
        discovery: ResourceDiscovery | None = None,
        governance_gate: ControlLoopGovernanceGate | None = None,
    ) -> None:
        self.discovery = discovery or ResourceDiscovery()
        self.governance_gate = governance_gate or ControlLoopGovernanceGate()

    def build(
        self,
        *,
        provider: CloudProvider,
        resource_type: str,
        resource_id: str,
    ) -> ResourceContextPipelineResult:
        discovered_resources = self.discovery.list_resources(
            provider=provider,
            resource_type=resource_type,
        )

        discovered = any(
            resource.resource_id == resource_id
            for resource in discovered_resources
        )

        governance = self.governance_gate.evaluate(
            provider=provider,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        observation = governance.resource.observation
        resource_context = ResourceContext(
            provider=observation.provider,
            resource_id=observation.resource_id,
            resource_type=observation.resource_type,
            observation=observation.as_dict(),
        )

        outcome = (
            "blocked"
            if governance.blocked
            else "review"
            if governance.requires_human_review
            else "allowed"
        )

        evidence = {
            "provider": provider.provider_name,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "discovered": discovered,
            "policy_decision": governance.decision.value,
            "allowed_for_decision": governance.allowed,
            "requires_human_review": governance.requires_human_review,
            "blocked": governance.blocked,
            "pipeline_outcome": outcome,
        }

        return ResourceContextPipelineResult(
            provider=provider.provider_name,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_context=resource_context,
            governance=governance,
            discovered=discovered,
            evidence=evidence,
        )
