from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

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
    governance: GovernedDecisionPipelineResult
    lifecycle: AutonomousLifecycleResult | None
    outcome: str
    execution_started: bool
    run_id: str
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
    """Bridge governed decisioning into the existing autonomous lifecycle."""

    def __init__(
        self,
        governed_pipeline: GovernedDecisionPipeline | None = None,
        lifecycle: AutonomousLifecycleOrchestrator | None = None,
    ) -> None:
        self.governed_pipeline = (
            governed_pipeline
            if governed_pipeline is not None
            else GovernedDecisionPipeline()
        )
        self.lifecycle = (
            lifecycle
            if lifecycle is not None
            else AutonomousLifecycleOrchestrator()
        )

    def run(
        self,
        provider: Any,
        action: ActionPlan,
        resource_type: str,
        resource_id: str,
        blast_radius: Any = None,
        dependency: Any = None,
        prediction: Any = None,
        cost_opportunity: Any = None,
        security_findings: Any = None,
        simulation: Any = None,
        memories: Any = None,
        approved_by: str | None = None,
        rejected_by: str | None = None,
        rejection_reason: str | None = None,
        idempotency_key: str | None = None,
        idempotency_seen: bool = False,
        dry_run: bool = True,
        run_id: str | None = None,
    ) -> GovernedAutonomousRunResult:
        trace_id = (run_id or "").strip() or str(uuid4())

        governance = self.governed_pipeline.evaluate(
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

        governance_evidence = getattr(governance, "evidence", None)
        if isinstance(governance_evidence, dict):
            evidence_governance = dict(governance_evidence)
        else:
            evidence_governance = {}

        evidence: dict[str, Any] = {
            "run_id": trace_id,
            "governance": evidence_governance,
            "governance_outcome": governance.recommendation,
            "provider": resource_id and getattr(provider, "provider_name", None),
            "resource_type": resource_type,
            "resource_id": resource_id,
            "lifecycle_started": False,
            "dry_run": dry_run,
        }

        if governance.blocked:
            evidence["execution_flow"] = "stopped_by_governance"
            return GovernedAutonomousRunResult(
                governance=governance,
                lifecycle=None,
                outcome="blocked",
                execution_started=False,
                run_id=trace_id,
                evidence=evidence,
            )

        if governance.requires_human_review:
            evidence["execution_flow"] = "stopped_for_human_review"
            return GovernedAutonomousRunResult(
                governance=governance,
                lifecycle=None,
                outcome="review",
                execution_started=False,
                run_id=trace_id,
                evidence=evidence,
            )

        if governance.decision is None:
            raise RuntimeError("Cannot continue without a decision")

        evidence["lifecycle_started"] = True
        evidence["execution_flow"] = "autonomous_lifecycle"
        evidence["decision_recommendation"] = governance.decision.recommendation.value
        evidence["decision_confidence"] = getattr(governance.decision, "confidence", None)
        evidence["trace"] = {
            "run_id": trace_id,
            "decision": governance.decision.recommendation.value,
            "action_id": getattr(action, "action_id", None),
            "resource_id": resource_id,
        }

        lifecycle_result = self.lifecycle.run(
            action=action,
            approved_by=approved_by,
            rejected_by=rejected_by,
            rejection_reason=rejection_reason,
            decision=governance.decision,
            blast_radius=blast_radius,
            idempotency_key=idempotency_key,
            idempotency_seen=idempotency_seen,
            dry_run=dry_run,
        )

        lifecycle_evidence = getattr(lifecycle_result, "evidence", None)
        if isinstance(lifecycle_evidence, dict):
            evidence["lifecycle"] = dict(lifecycle_evidence)
        evidence["lifecycle_outcome"] = lifecycle_result.outcome

        return GovernedAutonomousRunResult(
            governance=governance,
            lifecycle=lifecycle_result,
            outcome=lifecycle_result.outcome,
            execution_started=True,
            run_id=trace_id,
            evidence=evidence,
        )
