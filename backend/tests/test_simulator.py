from autonomy.action_models import ActionPlan, ActionTarget, RiskLevel
from autonomy.blast_radius import BlastRadius
from autonomy.simulator import SimulationOutcome, WhatIfSimulator


def create_action() -> ActionPlan:
    return ActionPlan(
        action_type="review_cpu_utilization",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-123",
        ),
        reason="Review CPU utilization.",
        risk=RiskLevel.LOW,
        requires_approval=True,
    )


def create_radius(
    score: int,
    risk: RiskLevel,
    dependents: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
) -> BlastRadius:
    return BlastRadius(
        direct_resources=("i-123",),
        dependent_resources=dependents,
        affected_services=services,
        impact_score=score,
        risk=risk,
        explanation="test radius",
        details={},
    )


def test_low_impact_simulation_is_safe():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(20, RiskLevel.LOW),
    )

    assert result.outcome == SimulationOutcome.SAFE
    assert result.predicted_status == "limited_direct_impact"
    assert result.impact_score == 20


def test_medium_impact_simulation_is_warning():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(40, RiskLevel.MEDIUM),
    )

    assert result.outcome == SimulationOutcome.WARNING
    assert result.predicted_status == "limited_infrastructure_impact"


def test_high_impact_simulation_is_high_impact():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(
            60,
            RiskLevel.HIGH,
            ("app-1",),
            ("payments",),
        ),
    )

    assert result.outcome == SimulationOutcome.HIGH_IMPACT
    assert result.predicted_status == "potential_service_impact"


def test_critical_simulation_is_blocked():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(
            90,
            RiskLevel.CRITICAL,
            ("app-1", "lb-1"),
            ("payments",),
        ),
    )

    assert result.outcome == SimulationOutcome.BLOCKED
    assert result.predicted_status == "significant_infrastructure_impact"


def test_affected_resources_are_combined():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(
            50,
            RiskLevel.MEDIUM,
            ("app-1", "lb-1"),
        ),
    )

    assert result.affected_resources == (
        "i-123",
        "app-1",
        "lb-1",
    )


def test_duplicate_affected_resources_are_removed():
    radius = BlastRadius(
        direct_resources=("i-123",),
        dependent_resources=("app-1", "app-1"),
        affected_services=("api", "api"),
        impact_score=50,
        risk=RiskLevel.MEDIUM,
        explanation="test",
        details={},
    )

    result = WhatIfSimulator().simulate(create_action(), radius)

    assert result.affected_resources == ("i-123", "app-1")
    assert result.affected_services == ("api",)


def test_simulation_never_mutates_infrastructure():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(20, RiskLevel.LOW),
    )

    assert result.details["infrastructure_mutation"] is False


def test_action_id_is_preserved():
    action = create_action()

    result = WhatIfSimulator().simulate(
        action,
        create_radius(20, RiskLevel.LOW),
    )

    assert result.action_id == action.action_id


def test_action_context_is_preserved():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(20, RiskLevel.LOW),
    )

    assert result.details["action_type"] == "review_cpu_utilization"
    assert result.details["resource_type"] == "ec2"
    assert result.details["resource_id"] == "i-123"


def test_explanation_contains_outcome():
    result = WhatIfSimulator().simulate(
        create_action(),
        create_radius(70, RiskLevel.HIGH),
    )

    assert "high_impact" in result.explanation
