from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from autonomy.action_models import ActionPlan, RiskLevel
from autonomy.blast_radius import BlastRadius


class SimulationOutcome(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    HIGH_IMPACT = "high_impact"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SimulationResult:
    action_id: str
    outcome: SimulationOutcome
    predicted_status: str
    impact_score: int
    risk: RiskLevel
    affected_resources: tuple[str, ...]
    affected_services: tuple[str, ...]
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)


class WhatIfSimulator:
    """Predict action impact without mutating infrastructure."""

    def simulate(
        self,
        action: ActionPlan,
        blast_radius: BlastRadius,
    ) -> SimulationResult:
        if not action.action_id:
            raise ValueError("action_id cannot be empty")

        affected_resources = tuple(
            dict.fromkeys(
                blast_radius.direct_resources
                + blast_radius.dependent_resources
            )
        )

        affected_services = tuple(
            dict.fromkeys(blast_radius.affected_services)
        )

        score = blast_radius.impact_score
        risk = blast_radius.risk

        if score >= 80 or risk == RiskLevel.CRITICAL:
            outcome = SimulationOutcome.BLOCKED
            predicted_status = "significant_infrastructure_impact"
        elif score >= 60 or risk == RiskLevel.HIGH:
            outcome = SimulationOutcome.HIGH_IMPACT
            predicted_status = "potential_service_impact"
        elif score >= 40 or risk == RiskLevel.MEDIUM:
            outcome = SimulationOutcome.WARNING
            predicted_status = "limited_infrastructure_impact"
        else:
            outcome = SimulationOutcome.SAFE
            predicted_status = "limited_direct_impact"

        if affected_resources:
            explanation = (
                f"Simulation predicts {outcome.value} impact for action "
                f"{action.action_id}; {len(affected_resources)} resource(s) "
                f"may be affected."
            )
        else:
            explanation = (
                f"Simulation predicts {outcome.value} impact for action "
                f"{action.action_id}."
            )

        return SimulationResult(
            action_id=action.action_id,
            outcome=outcome,
            predicted_status=predicted_status,
            impact_score=score,
            risk=risk,
            affected_resources=affected_resources,
            affected_services=affected_services,
            explanation=explanation,
            details={
                "action_type": action.action_type,
                "resource_type": action.target.resource_type,
                "resource_id": action.target.resource_id,
                "infrastructure_mutation": False,
            },
        )
