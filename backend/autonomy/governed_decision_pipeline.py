"""Governed resource-to-decision pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.action_models import ActionPlan
from autonomy.decision_intelligence import (
    DecisionContext,
    DecisionIntelligenceEngine,
    DecisionResult,
)
from autonomy.resource_context_pipeline import (
    ResourceContextPipeline,
    ResourceContextPipelineResult,
)


@dataclass(frozen=True)
class GovernedDecisionPipelineResult:
    resource_pipeline: ResourceContextPipelineResult
    decision: DecisionResult | None
    allowed_for_decision: bool
    requires_human_review: bool
    blocked: bool
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def recommendation(self) -> str | None:
        if self.decision is None:
            if self.blocked:
                return "deny"
            if self.requires_human_review:
                return "review"
            return None
        return self.decision.recommendation.value


class GovernedDecisionPipeline:
    """Run resource governance before invoking Decision Intelligence."""

    def __init__(
        self,
        *,
        resource_pipeline: ResourceContextPipeline | None = None,
        decision_engine: DecisionIntelligenceEngine | None = None,
    ) -> None:
        self.resource_pipeline = resource_pipeline or ResourceContextPipeline()
        self.decision_engine = decision_engine or DecisionIntelligenceEngine()

    def evaluate(
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
    ) -> GovernedDecisionPipelineResult:
        if not resource_type.strip():
            raise ValueError("resource_type cannot be empty")
        if not resource_id.strip():
            raise ValueError("resource_id cannot be empty")
        if action is None:
            raise ValueError("action cannot be None")
        if action.target.resource_id != resource_id:
            raise ValueError("action target does not match resource_id")

        pipeline = self.resource_pipeline.build(
            provider=provider,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        evidence = {
            "resource_pipeline": dict(pipeline.evidence),
            "governance": dict(pipeline.governance.evidence),
            "provider": pipeline.provider,
            "resource_type": pipeline.resource_type,
            "resource_id": pipeline.resource_id,
            "allowed_for_decision": pipeline.allowed_for_decision,
            "requires_human_review": pipeline.requires_human_review,
            "blocked": pipeline.blocked,
        }

        if not pipeline.allowed_for_decision:
            evidence.update(
                {
                    "decision_evaluated": False,
                    "decision_flow": "stopped_by_governance",
                }
            )
            return GovernedDecisionPipelineResult(
                resource_pipeline=pipeline,
                decision=None,
                allowed_for_decision=False,
                requires_human_review=pipeline.requires_human_review,
                blocked=pipeline.blocked,
                evidence=evidence,
            )

        context = DecisionContext(
            resource_id=resource_id,
            resource_type=resource_type,
            action=action,
            provider=pipeline.provider,
            resource_context=pipeline.resource_context,
            blast_radius=blast_radius,
            dependency=dependency,
            prediction=prediction,
            cost_opportunity=cost_opportunity,
            security_findings=list(security_findings or []),
            simulation=simulation,
            memories=list(memories or []),
        )

        decision = self.decision_engine.evaluate(context)
        evidence.update(
            {
                "decision_evaluated": True,
                "decision_flow": "decision_intelligence",
                "decision_recommendation": decision.recommendation.value,
                "decision_confidence": decision.confidence,
                "decision": dict(decision.evidence),
            }
        )

        return GovernedDecisionPipelineResult(
            resource_pipeline=pipeline,
            decision=decision,
            allowed_for_decision=True,
            requires_human_review=False,
            blocked=False,
            evidence=evidence,
        )
