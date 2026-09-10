from autonomy.context_graph import ContextGraph


def build_graph() -> ContextGraph:
    graph = ContextGraph()

    graph.add_node("ec2", "i-123")
    graph.add_node("application", "app-1")
    graph.add_node("load_balancer", "lb-1")
    graph.add_node("service", "payments")

    graph.add_relationship("app-1", "i-123", "runs_on")
    graph.add_relationship("lb-1", "app-1", "routes_to")
    graph.add_relationship("payments", "app-1", "uses")

    return graph


def test_add_node():
    graph = ContextGraph()

    node = graph.add_node(
        "ec2",
        "i-123",
        {"environment": "production"},
    )

    assert node.resource_type == "ec2"
    assert node.resource_id == "i-123"
    assert node.metadata["environment"] == "production"
    assert graph.get_node("i-123") == node


def test_add_relationship():
    graph = ContextGraph()
    graph.add_node("ec2", "i-123")
    graph.add_node("application", "app-1")

    edge = graph.add_relationship(
        "app-1",
        "i-123",
        "runs_on",
    )

    assert edge.source_id == "app-1"
    assert edge.target_id == "i-123"
    assert edge.relationship == "runs_on"


def test_dependents_are_resolved():
    graph = build_graph()

    dependents = graph.get_dependents("i-123")

    assert [node.resource_id for node in dependents] == ["app-1"]


def test_dependencies_are_resolved():
    graph = build_graph()

    dependencies = graph.get_dependencies("app-1")

    assert [node.resource_id for node in dependencies] == ["i-123"]


def test_multiple_relationships_are_resolved():
    graph = build_graph()

    dependencies = graph.get_dependencies("payments")

    assert [node.resource_id for node in dependencies] == ["app-1"]


def test_duplicate_relationship_is_not_added():
    graph = ContextGraph()
    graph.add_node("ec2", "i-123")
    graph.add_node("application", "app-1")

    graph.add_relationship("app-1", "i-123", "runs_on")
    graph.add_relationship("app-1", "i-123", "runs_on")

    assert len(graph.get_edges()) == 1


def test_missing_source_is_rejected():
    graph = ContextGraph()
    graph.add_node("ec2", "i-123")

    try:
        graph.add_relationship("missing", "i-123", "depends_on")
    except ValueError as exc:
        assert "Source resource not found" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_missing_target_is_rejected():
    graph = ContextGraph()
    graph.add_node("ec2", "i-123")

    try:
        graph.add_relationship("i-123", "missing", "depends_on")
    except ValueError as exc:
        assert "Target resource not found" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_empty_resource_id_is_rejected():
    graph = ContextGraph()

    try:
        graph.add_node("ec2", "")
    except ValueError as exc:
        assert str(exc) == "resource_id cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_empty_relationship_is_rejected():
    graph = ContextGraph()
    graph.add_node("ec2", "i-123")
    graph.add_node("application", "app-1")

    try:
        graph.add_relationship("app-1", "i-123", "")
    except ValueError as exc:
        assert str(exc) == "relationship cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_clear_removes_graph():
    graph = build_graph()

    graph.clear()

    assert graph.get_node("i-123") is None
    assert graph.get_edges() == []
