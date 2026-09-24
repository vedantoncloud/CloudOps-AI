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
class GovernedAutonomousRunResult:
    """Result of the governed decision -> autonomous lifecycle bridge."""

    governance: GovernedDecisionPipelineResult
    lifecycle: AutonomousLifecycleResult | None
    outcome: str
    execution_started: bool
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.outcome == "blocked"

    @property
    def requires_human_review(self) -> bool:
        return self.outcome == "review"

    @property
    def completed(self) -> bool:
        return self.lifecycle is not None and self.lifecycle.completed


class GovernedAutonomousRun:
    """Connect governed decisioning to the existing bounded lifecycle.

    Governance is authoritative: DENY and REVIEW stop before lifecycle
    execution. Only an ALLOW decision is handed to the existing lifecycle,
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
    ) -> GovernedAutonomousRunResult:
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
            "governance": dict(governed.evidence),
            "provider": governed.resource_pipeline.provider,
            "resource_type": governed.resource_pipeline.resource_type,
            "resource_id": governed.resource_pipeline.resource_id,
            "governance_outcome": (
                "deny"
                if governed.blocked
                else "review"
                if governed.requires_human_review
                else "allow"
            ),
            "lifecycle_started": False,
            "dry_run": dry_run,
        }

        if governed.blocked:
            evidence["execution_flow"] = "stopped_by_governance"
            return GovernedAutonomousRunResult(
                governance=governed,
                lifecycle=None,
                outcome="blocked",
                execution_started=False,
                evidence=evidence,
            )

        if governed.requires_human_review:
            evidence["execution_flow"] = "stopped_for_human_review"
            return GovernedAutonomousRunResult(
                governance=governed,
                lifecycle=None,
                outcome="review",
                execution_started=False,
                evidence=evidence,
            )

        if governed.decision is None:
            raise RuntimeError(
                "Governed pipeline allowed execution without a decision result."
            )

        lifecycle_result = self.lifecycle.run(
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
                "execution_flow": "autonomous_lifecycle",
                "lifecycle_started": True,
                "lifecycle_outcome": lifecycle_result.outcome,
                "lifecycle": dict(lifecycle_result.evidence),
            }
        )

        return GovernedAutonomousRunResult(
            governance=governed,
            lifecycle=lifecycle_result,
            outcome=lifecycle_result.outcome,
            execution_started=True,
            evidence=evidence,
        )
