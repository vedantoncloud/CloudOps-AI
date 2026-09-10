from autonomy.context_blast_radius import ContextGraphBlastRadiusAnalyzer
from autonomy.context_graph import ContextGraph


def build_graph() -> ContextGraph:
    graph = ContextGraph()

    graph.add_node("ec2", "i-123")
    graph.add_node("application", "app-1")
    graph.add_node("load_balancer", "lb-1")
    graph.add_node("service", "payments")

    graph.add_relationship("app-1", "i-123", "runs_on")
    graph.add_relationship("lb-1", "i-123", "routes_to")
    graph.add_relationship("payments", "i-123", "depends_on")

    return graph


def test_context_graph_drives_blast_radius():
    graph = build_graph()
    analyzer = ContextGraphBlastRadiusAnalyzer(graph)

    result = analyzer.analyze("i-123")

    assert result.direct_resources == ("i-123",)
    assert set(result.dependent_resources) == {
        "app-1",
        "lb-1",
        "payments",
    }
    assert set(result.affected_services) == {
        "app-1",
        "payments",
    }
    assert result.impact_score == 100


def test_context_graph_blast_radius_rejects_unknown_resource():
    graph = ContextGraph()
    analyzer = ContextGraphBlastRadiusAnalyzer(graph)

    try:
        analyzer.analyze("missing")
    except ValueError as exc:
        assert "Resource not found in context graph" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_context_graph_without_dependents_has_low_impact():
    graph = ContextGraph()
    graph.add_node("ec2", "i-123")

    analyzer = ContextGraphBlastRadiusAnalyzer(graph)
    result = analyzer.analyze("i-123")

    assert result.dependent_resources == ()
    assert result.affected_services == ()
    assert result.impact_score == 20
