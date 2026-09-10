from dataclasses import dataclass

from autonomy.action_models import ActionPlan
from autonomy.blast_radius import BlastRadius
from autonomy.context_graph import ContextGraph
from autonomy.action_models import RiskLevel


@dataclass(frozen=True)
class DependencyAction:
    action: ActionPlan
    impact_score: int
    risk: RiskLevel
    blocked: bool
    depends_on: tuple[str, ...]
    reason: str


class DependencyAwarePlanner:
    """Order and gate actions using infrastructure dependencies and blast radius."""

    def __init__(self, graph: ContextGraph) -> None:
        self.graph = graph

    def evaluate_action(
        self,
        action: ActionPlan,
        blast_radius: BlastRadius,
    ) -> DependencyAction:
        resource_id = action.target.resource_id
        node = self.graph.get_node(resource_id)

        if node is None:
            raise ValueError(
                f"Resource not found in context graph: {resource_id}"
            )

        dependents = tuple(
            dependent.resource_id
            for dependent in self.graph.get_dependents(resource_id)
        )

        blocked = (
            blast_radius.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            or blast_radius.impact_score >= 60
        )

        if blocked:
            reason = (
                f"Action requires additional governance because resource "
                f"{resource_id} has impact score {blast_radius.impact_score} "
                f"and risk {blast_radius.risk.value}."
            )
        else:
            reason = (
                f"Action is dependency-aware with impact score "
                f"{blast_radius.impact_score} and risk "
                f"{blast_radius.risk.value}."
            )

        return DependencyAction(
            action=action,
            impact_score=blast_radius.impact_score,
            risk=blast_radius.risk,
            blocked=blocked,
            depends_on=dependents,
            reason=reason,
        )

    def order_actions(
        self,
        actions: list[DependencyAction],
    ) -> list[DependencyAction]:
        """Prioritize lower-impact actions before higher-impact actions."""
        return sorted(
            actions,
            key=lambda item: (
                item.blocked,
                item.impact_score,
                item.action.target.resource_id,
            ),
        )
