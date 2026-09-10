from autonomy.action_models import (
    ActionPlan,
    ActionTarget,
    RiskLevel,
)
from autonomy.blast_radius import BlastRadius
from autonomy.context_graph import ContextGraph
from autonomy.dependency_planner import DependencyAwarePlanner


def create_action(resource_id: str) -> ActionPlan:
    return ActionPlan(
        action_type="review_cpu_utilization",
        target=ActionTarget(
            resource_type="ec2",
            resource_id=resource_id,
        ),
        reason="Review CPU utilization.",
        risk=RiskLevel.LOW,
        requires_approval=True,
    )


def create_graph() -> ContextGraph:
    graph = ContextGraph()
    graph.add_node("ec2", "i-123")
    graph.add_node("application", "app-1")
    graph.add_node("ec2", "i-456")
    graph.add_node("application", "app-2")

    graph.add_relationship("app-1", "i-123", "runs_on")
    graph.add_relationship("app-2", "i-456", "runs_on")

    return graph


def create_radius(
    resource_id: str,
    impact_score: int,
    risk: RiskLevel,
    dependents: tuple[str, ...] = (),
) -> BlastRadius:
    return BlastRadius(
        direct_resources=(resource_id,),
        dependent_resources=dependents,
        affected_services=(),
        impact_score=impact_score,
        risk=risk,
        explanation="test blast radius",
        details={},
    )


def test_low_impact_action_is_not_blocked():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    action = create_action("i-123")
    radius = create_radius("i-123", 20, RiskLevel.LOW)

    result = planner.evaluate_action(action, radius)

    assert result.blocked is False
    assert result.impact_score == 20
    assert result.risk == RiskLevel.LOW


def test_high_risk_action_is_blocked():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    action = create_action("i-123")
    radius = create_radius("i-123", 70, RiskLevel.HIGH, ("app-1",))

    result = planner.evaluate_action(action, radius)

    assert result.blocked is True
    assert result.risk == RiskLevel.HIGH
    assert result.depends_on == ("app-1",)


def test_critical_action_is_blocked():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    action = create_action("i-123")
    radius = create_radius("i-123", 90, RiskLevel.CRITICAL)

    result = planner.evaluate_action(action, radius)

    assert result.blocked is True
    assert result.risk == RiskLevel.CRITICAL


def test_impact_score_60_is_blocked():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    action = create_action("i-123")
    radius = create_radius("i-123", 60, RiskLevel.MEDIUM)

    result = planner.evaluate_action(action, radius)

    assert result.blocked is True


def test_dependencies_are_exposed():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    action = create_action("i-123")
    radius = create_radius("i-123", 30, RiskLevel.LOW)

    result = planner.evaluate_action(action, radius)

    assert result.depends_on == ("app-1",)


def test_unknown_resource_is_rejected():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    action = create_action("missing")
    radius = create_radius("missing", 20, RiskLevel.LOW)

    try:
        planner.evaluate_action(action, radius)
    except ValueError as exc:
        assert "Resource not found in context graph" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_order_actions_prioritizes_lower_impact():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    low = planner.evaluate_action(
        create_action("i-123"),
        create_radius("i-123", 20, RiskLevel.LOW),
    )
    medium = planner.evaluate_action(
        create_action("i-456"),
        create_radius("i-456", 50, RiskLevel.MEDIUM),
    )

    ordered = planner.order_actions([medium, low])

    assert [item.action.target.resource_id for item in ordered] == [
        "i-123",
        "i-456",
    ]


def test_blocked_actions_are_ordered_after_safe_actions():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    safe = planner.evaluate_action(
        create_action("i-123"),
        create_radius("i-123", 20, RiskLevel.LOW),
    )
    blocked = planner.evaluate_action(
        create_action("i-456"),
        create_radius("i-456", 80, RiskLevel.HIGH),
    )

    ordered = planner.order_actions([blocked, safe])

    assert ordered[0].blocked is False
    assert ordered[1].blocked is True


def test_equal_impact_uses_resource_id_for_deterministic_order():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    first = planner.evaluate_action(
        create_action("i-456"),
        create_radius("i-456", 20, RiskLevel.LOW),
    )
    second = planner.evaluate_action(
        create_action("i-123"),
        create_radius("i-123", 20, RiskLevel.LOW),
    )

    ordered = planner.order_actions([first, second])

    assert [item.action.target.resource_id for item in ordered] == [
        "i-123",
        "i-456",
    ]


def test_reason_contains_risk_and_impact():
    graph = create_graph()
    planner = DependencyAwarePlanner(graph)

    action = create_action("i-123")
    radius = create_radius("i-123", 75, RiskLevel.HIGH)

    result = planner.evaluate_action(action, radius)

    assert "75" in result.reason
    assert "high" in result.reason
