from dataclasses import dataclass, field
from typing import Any

from autonomy.action_models import RiskLevel


@dataclass(frozen=True)
class ResourceDependency:
    resource_type: str
    resource_id: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlastRadius:
    direct_resources: tuple[str, ...]
    dependent_resources: tuple[str, ...]
    affected_services: tuple[str, ...]
    impact_score: int
    risk: RiskLevel
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)


class BlastRadiusAnalyzer:
    """Analyze the potential impact of an infrastructure action."""

    def analyze(
        self,
        *,
        resource_id: str,
        dependencies: list[ResourceDependency] | None = None,
        affected_services: list[str] | None = None,
    ) -> BlastRadius:
        if not resource_id or not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        dependencies = dependencies or []
        affected_services = affected_services or []

        dependent_resources = []
        for dependency in dependencies:
            if resource_id in dependency.depends_on:
                dependent_resources.append(dependency.resource_id)

        dependent_resources = list(dict.fromkeys(dependent_resources))
        services = list(dict.fromkeys(affected_services))

        impact_score = min(
            100,
            20
            + len(dependent_resources) * 15
            + len(services) * 20,
        )

        if impact_score >= 80:
            risk = RiskLevel.CRITICAL
        elif impact_score >= 60:
            risk = RiskLevel.HIGH
        elif impact_score >= 40:
            risk = RiskLevel.MEDIUM
        else:
            risk = RiskLevel.LOW

        if dependent_resources or services:
            explanation = (
                f"Resource {resource_id} has "
                f"{len(dependent_resources)} dependent resource(s) "
                f"and {len(services)} affected service(s)."
            )
        else:
            explanation = (
                f"Resource {resource_id} has no known dependent resources "
                "or affected services."
            )

        return BlastRadius(
            direct_resources=(resource_id,),
            dependent_resources=tuple(dependent_resources),
            affected_services=tuple(services),
            impact_score=impact_score,
            risk=risk,
            explanation=explanation,
            details={
                "dependent_resource_count": len(dependent_resources),
                "affected_service_count": len(services),
            },
        )
