"""Unified governed autonomous control-plane run bridge.

Connects resource governance and Decision Intelligence to the existing
autonomous lifecycle without duplicating execution, approval, verification,
or audit logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.action_models import ActionPlan
from autonomy.autonomous_lifecycle import (
    AutonomousLifecycleOrchestrator,
    AutonomousLifecycleResult,
)
from autonomy.governed_decision_pipeline import (
    GovernedDecisionPipeline,
    GovernedDecisionPipelineResult,
)


@dataclass(frozen=True)
class AutonomousControlPlaneResult:
    """Result of one governed control-plane run."""

    governed: GovernedDecisionPipelineResult
    lifecycle: AutonomousLifecycleResult | None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        if self.lifecycle is not None:
            return self.lifecycle.outcome
        if self.governed.blocked:
            return "blocked"
        if self.governed.requires_human_review:
            return "awaiting_approval"
        return "not_executed"

    @property
    def executed(self) -> bool:
        return self.lifecycle is not None and self.lifecycle.execution is not None


class AutonomousControlPlane:
    """Unified governed entry point for autonomous infrastructure actions.

    Governance and Decision Intelligence are evaluated first. Only an
    ALLOW/decision-producing result is handed to the existing lifecycle,
    which remains responsible for safety, approval, execution, verification,
    and audit.
    """

    def __init__(
        self,
        *,
        governed_pipeline: GovernedDecisionPipeline | None = None,
        lifecycle: AutonomousLifecycleOrchestrator | None = None,
    ) -> None:
        self.governed_pipeline = governed_pipeline or GovernedDecisionPipeline()
        self.lifecycle = lifecycle or AutonomousLifecycleOrchestrator()

    def run(
        self,
        *,
        provider: Any,
        action: ActionPlan,
        resource_type: str,
        resource_id: str,
        blast_radius: Any | None = None,
        dependency: Any | None = None,
        prediction: Any | None = None,
        cost_opportunity: Any | None = None,
        security_findings: list[Any] | None = None,
        simulation: Any | None = None,
        memories: list[Any] | None = None,
        approved_by: str | None = None,
        rejected_by: str | None = None,
        rejection_reason: str | None = None,
        idempotency_key: str | None = None,
        idempotency_seen: bool = False,
        dry_run: bool = True,
    ) -> AutonomousControlPlaneResult:
        governed = self.governed_pipeline.evaluate(
            provider=provider,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            blast_radius=blast_radius,
            dependency=dependency,
            prediction=prediction,
            cost_opportunity=cost_opportunity,
            security_findings=security_findings,
            simulation=simulation,
            memories=memories,
        )

        evidence: dict[str, Any] = {
            "control_plane_flow": "governance_decision_lifecycle",
            "governed": dict(governed.evidence),
            "governance_allowed": governed.allowed_for_decision,
            "decision_evaluated": governed.decision is not None,
        }

        if not governed.allowed_for_decision or governed.decision is None:
            evidence["lifecycle_executed"] = False
            evidence["execution_flow"] = "stopped_before_lifecycle"
            return AutonomousControlPlaneResult(
                governed=governed,
                lifecycle=None,
                evidence=evidence,
            )

        lifecycle = self.lifecycle.run(
            action,
            approved_by=approved_by,
            rejected_by=rejected_by,
            rejection_reason=rejection_reason,
            decision=governed.decision,
            blast_radius=blast_radius,
            idempotency_key=idempotency_key,
            idempotency_seen=idempotency_seen,
            dry_run=dry_run,
        )

        evidence.update(
            {
                "lifecycle_executed": True,
                "execution_flow": "autonomous_lifecycle",
                "lifecycle_outcome": lifecycle.outcome,
                "lifecycle_evidence": dict(lifecycle.evidence),
            }
        )

        return AutonomousControlPlaneResult(
            governed=governed,
            lifecycle=lifecycle,
            evidence=evidence,
        )
