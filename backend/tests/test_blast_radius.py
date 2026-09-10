from autonomy.action_models import RiskLevel
from autonomy.blast_radius import BlastRadiusAnalyzer, ResourceDependency


def test_no_dependencies_has_low_impact():
    analyzer = BlastRadiusAnalyzer()

    result = analyzer.analyze(resource_id="i-123")

    assert result.direct_resources == ("i-123",)
    assert result.dependent_resources == ()
    assert result.affected_services == ()
    assert result.impact_score == 20
    assert result.risk == RiskLevel.LOW


def test_dependent_resources_increase_impact():
    analyzer = BlastRadiusAnalyzer()

    dependencies = [
        ResourceDependency(
            resource_type="application",
            resource_id="app-1",
            depends_on=("i-123",),
        ),
        ResourceDependency(
            resource_type="load_balancer",
            resource_id="lb-1",
            depends_on=("i-123",),
        ),
    ]

    result = analyzer.analyze(
        resource_id="i-123",
        dependencies=dependencies,
    )

    assert result.dependent_resources == ("app-1", "lb-1")
    assert result.impact_score == 50
    assert result.risk == RiskLevel.MEDIUM


def test_affected_services_increase_impact():
    analyzer = BlastRadiusAnalyzer()

    result = analyzer.analyze(
        resource_id="i-123",
        affected_services=["payments", "checkout"],
    )

    assert result.affected_services == ("payments", "checkout")
    assert result.impact_score == 60
    assert result.risk == RiskLevel.HIGH


def test_high_dependency_count_can_be_critical():
    analyzer = BlastRadiusAnalyzer()

    dependencies = [
        ResourceDependency(
            resource_type="service",
            resource_id=f"service-{index}",
            depends_on=("i-123",),
        )
        for index in range(5)
    ]

    result = analyzer.analyze(
        resource_id="i-123",
        dependencies=dependencies,
        affected_services=["payments"],
    )

    assert result.impact_score == 100
    assert result.risk == RiskLevel.CRITICAL


def test_duplicate_dependencies_are_removed():
    analyzer = BlastRadiusAnalyzer()

    dependencies = [
        ResourceDependency(
            resource_type="service",
            resource_id="app-1",
            depends_on=("i-123",),
        ),
        ResourceDependency(
            resource_type="service",
            resource_id="app-1",
            depends_on=("i-123",),
        ),
    ]

    result = analyzer.analyze(
        resource_id="i-123",
        dependencies=dependencies,
    )

    assert result.dependent_resources == ("app-1",)
    assert result.impact_score == 35


def test_duplicate_services_are_removed():
    analyzer = BlastRadiusAnalyzer()

    result = analyzer.analyze(
        resource_id="i-123",
        affected_services=["api", "api", "payments"],
    )

    assert result.affected_services == ("api", "payments")
    assert result.impact_score == 60


def test_unrelated_dependencies_are_ignored():
    analyzer = BlastRadiusAnalyzer()

    dependencies = [
        ResourceDependency(
            resource_type="ec2",
            resource_id="i-999",
            depends_on=("i-other",),
        )
    ]

    result = analyzer.analyze(
        resource_id="i-123",
        dependencies=dependencies,
    )

    assert result.dependent_resources == ()
    assert result.impact_score == 20


def test_empty_resource_id_is_rejected():
    analyzer = BlastRadiusAnalyzer()

    try:
        analyzer.analyze(resource_id="")
    except ValueError as exc:
        assert str(exc) == "resource_id cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_explanation_contains_impact_information():
    analyzer = BlastRadiusAnalyzer()

    dependencies = [
        ResourceDependency(
            resource_type="application",
            resource_id="app-1",
            depends_on=("i-123",),
        )
    ]

    result = analyzer.analyze(
        resource_id="i-123",
        dependencies=dependencies,
        affected_services=["payments"],
    )

    assert "i-123" in result.explanation
    assert "1 dependent resource(s)" in result.explanation
    assert "1 affected service(s)" in result.explanation


def test_details_contain_counts():
    analyzer = BlastRadiusAnalyzer()

    result = analyzer.analyze(
        resource_id="i-123",
        affected_services=["api"],
    )

    assert result.details["dependent_resource_count"] == 0
    assert result.details["affected_service_count"] == 1
