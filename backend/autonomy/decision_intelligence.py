from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from autonomy.action_models import ActionPlan, RiskLevel
from autonomy.blast_radius import BlastRadius
from autonomy.cost_optimizer import CostOpportunity
from autonomy.dependency_planner import DependencyAction
from autonomy.operational_memory import OperationalMemory
from autonomy.predictive import PredictionResult
from autonomy.security_remediation import SecurityFinding, SecurityRemediationEngine
from autonomy.simulator import SimulationResult


class DecisionRecommendation(str, Enum):
    PROCEED = "proceed"
    REVIEW = "review"
    BLOCK = "block"
    DEFER = "defer"


@dataclass(frozen=True)
class DecisionContext:
    resource_id: str
    resource_type: str
    action: ActionPlan
    blast_radius: BlastRadius | None = None
    dependency: DependencyAction | None = None
    prediction: PredictionResult | None = None
    cost_opportunity: CostOpportunity | None = None
    security_findings: list[SecurityFinding] = field(default_factory=list)
    simulation: SimulationResult | None = None
    memories: list[OperationalMemory] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionResult:
    resource_id: str
    action_id: str
    recommendation: DecisionRecommendation
    risk: RiskLevel
    confidence: float
    reasons: list[str]
    preventive: bool
    requires_human_review: bool
    evidence: dict[str, Any] = field(default_factory=dict)


class DecisionIntelligenceEngine:
    """Combine operational signals into a governed action recommendation."""

    def evaluate(self, context: DecisionContext) -> DecisionResult:
        if not context.resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        if not context.resource_type.strip():
            raise ValueError("resource_type cannot be empty")

        if context.action.target.resource_id != context.resource_id:
            raise ValueError("action target does not match resource_id")

        reasons: list[str] = []
        evidence: dict[str, Any] = {}
        risk = context.action.risk
        recommendation = DecisionRecommendation.PROCEED
        preventive = False

        if context.blast_radius is not None:
            evidence["impact_score"] = context.blast_radius.impact_score
            evidence["blast_radius_risk"] = context.blast_radius.risk.value

            if context.blast_radius.risk in {
                RiskLevel.CRITICAL,
                RiskLevel.HIGH,
            }:
                risk = RiskLevel.CRITICAL if context.blast_radius.risk == RiskLevel.CRITICAL else RiskLevel.HIGH
                recommendation = DecisionRecommendation.REVIEW
                reasons.append(
                    "Blast radius indicates elevated infrastructure impact."
                )

        if context.dependency is not None:
            evidence["dependency_blocked"] = context.dependency.blocked
            evidence["dependency_impact_score"] = context.dependency.impact_score

            if context.dependency.blocked:
                recommendation = DecisionRecommendation.BLOCK
                risk = max(
                    (risk, context.dependency.risk),
                    key=lambda item: list(RiskLevel).index(item),
                )
                reasons.append(
                    "Dependency analysis blocks the action because impact is too high."
                )

        if context.prediction is not None:
            evidence["predicted_value"] = context.prediction.predicted_value
            evidence["prediction_signal"] = context.prediction.signal.value
            evidence["prediction_confidence"] = context.prediction.confidence

            if context.prediction.predicted_risk in {
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            }:
                preventive = True
                reasons.append(
                    "Predictive analysis indicates elevated future operational risk."
                )

        if context.cost_opportunity is not None:
            evidence["cost_signal"] = context.cost_opportunity.signal.value
            evidence["cost_confidence"] = context.cost_opportunity.confidence

            if context.cost_opportunity.estimated_monthly_savings is not None:
                evidence["estimated_savings"] = (
                    context.cost_opportunity.estimated_monthly_savings
                )
                reasons.append(
                    "Cost analysis identified a measurable optimization opportunity."
                )

        if context.security_findings:
            severities = [finding.severity for finding in context.security_findings]
            highest_security_risk = max(
                severities,
                key=lambda item: list(RiskLevel).index(item),
            )

            evidence["security_finding_count"] = len(context.security_findings)
            evidence["highest_security_risk"] = highest_security_risk.value

            if highest_security_risk == RiskLevel.CRITICAL:
                recommendation = DecisionRecommendation.BLOCK
                risk = RiskLevel.CRITICAL
                reasons.append(
                    "Critical security findings require blocking automatic action."
                )
            elif highest_security_risk == RiskLevel.HIGH:
                recommendation = DecisionRecommendation.REVIEW
                risk = RiskLevel.HIGH
                reasons.append(
                    "High-severity security findings require human review."
                )

        if context.simulation is not None:
            evidence["simulation_outcome"] = context.simulation.outcome.value

            if context.simulation.outcome.value == "blocked":
                recommendation = DecisionRecommendation.BLOCK
                reasons.append("What-if simulation blocked the proposed action.")
            elif context.simulation.outcome.value == "high_impact":
                recommendation = DecisionRecommendation.REVIEW
                reasons.append(
                    "What-if simulation predicts high infrastructure impact."
                )

        successful_memories = sum(
            1
            for memory in context.memories
            if memory.outcome.value == "success"
        )
        failed_memories = sum(
            1
            for memory in context.memories
            if memory.outcome.value == "failure"
        )

        evidence["historical_memories"] = len(context.memories)
        evidence["historical_successes"] = successful_memories
        evidence["historical_failures"] = failed_memories

        if failed_memories > successful_memories and failed_memories > 0:
            recommendation = DecisionRecommendation.REVIEW
            reasons.append(
                "Historical operational memory contains more failures than successes for this situation."
            )
        elif successful_memories > 0:
            reasons.append(
                "Historical operational memory contains previously successful outcomes."
            )

        if context.action.requires_approval:
            requires_human_review = True
            if recommendation == DecisionRecommendation.PROCEED:
                recommendation = DecisionRecommendation.REVIEW
            reasons.append("Action is approval-gated by autonomy policy.")
        else:
            requires_human_review = recommendation in {
                DecisionRecommendation.REVIEW,
                DecisionRecommendation.BLOCK,
            }

        if recommendation == DecisionRecommendation.BLOCK:
            confidence = 0.95
        elif recommendation == DecisionRecommendation.REVIEW:
            confidence = 0.85
        elif preventive:
            confidence = 0.80
        else:
            confidence = 0.70

        if not reasons:
            reasons.append("No elevated risk signals were detected.")

        return DecisionResult(
            resource_id=context.resource_id,
            action_id=context.action.action_id,
            recommendation=recommendation,
            risk=risk,
            confidence=confidence,
            reasons=reasons,
            preventive=preventive,
            requires_human_review=requires_human_review,
            evidence=evidence,
        )

