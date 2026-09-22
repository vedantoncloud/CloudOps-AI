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

    Discovery is best-effort because provider adapters used by the control
    loop may expose observation/get_resource without inventory-list methods.
    Governance remains authoritative for whether a resource may proceed.
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
        discovery_error: str | None = None

        try:
            discovered_resources = self.discovery.list_resources(
                provider=provider.provider_name,
                resource_type=resource_type,
            )
            discovered = any(
                resource.resource_id == resource_id
                for resource in discovered_resources
            )
        except (AttributeError, KeyError, ValueError) as exc:
            # Some provider test doubles / adapters intentionally implement
            # only read-only observation. Do not let optional inventory
            # capabilities prevent governance and decision evaluation.
            discovered_resources = []
            discovered = False
            discovery_error = str(exc)

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

        if governance.blocked:
            outcome = "blocked"
        elif governance.requires_human_review:
            outcome = "review"
        else:
            outcome = "allowed"

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

        if discovery_error is not None:
            evidence["discovery_available"] = False
            evidence["discovery_error"] = discovery_error
        else:
            evidence["discovery_available"] = True
            evidence["discovered_resource_count"] = len(discovered_resources)

        return ResourceContextPipelineResult(
            provider=provider.provider_name,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_context=resource_context,
            governance=governance,
            discovered=discovered,
            evidence=evidence,
        )
