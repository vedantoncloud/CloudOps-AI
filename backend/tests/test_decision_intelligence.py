from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.blast_radius import BlastRadius
from autonomy.cost_optimizer import CostOpportunity, CostSignal
from autonomy.dependency_planner import DependencyAction
from autonomy.decision_intelligence import (
    DecisionContext,
    DecisionIntelligenceEngine,
    DecisionRecommendation,
)
from autonomy.operational_memory import (
    MemoryOutcome,
    OperationalMemory,
)
from autonomy.predictive import (
    PredictionResult,
    PredictionSignal,
)
from autonomy.security_remediation import (
    SecurityFinding,
    SecurityFindingType,
)
from autonomy.simulator import SimulationOutcome, SimulationResult


def make_action(
    *,
    action_id="action-1",
    risk=RiskLevel.MEDIUM,
    requires_approval=True,
):
    return ActionPlan(
        action_id=action_id,
        action_type="investigate_cpu_capacity",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-123",
        ),
        reason="High CPU utilization detected",
        risk=risk,
        requires_approval=requires_approval,
        status=ActionStatus.PENDING_APPROVAL,
    )


def make_blast_radius(
    *,
    score=20,
    risk=RiskLevel.LOW,
):
    return BlastRadius(
        direct_resources=["i-123"],
        dependent_resources=[],
        affected_services=[],
        impact_score=score,
        risk=risk,
        explanation="Test blast radius",
        details={},
    )


def make_prediction(
    *,
    risk=RiskLevel.LOW,
    signal=PredictionSignal.STABLE,
):
    return PredictionResult(
        resource_id="i-123",
        metric="cpu",
        signal=signal,
        predicted_risk=risk,
        predicted_value=50,
        confidence=0.80,
        recommendation="Monitor",
        reason="Test prediction",
        details={},
    )


def make_memory(*, outcome=MemoryOutcome.SUCCESS):
    return OperationalMemory(
        memory_id="memory-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU utilization detected",
        action="investigate_cpu_capacity",
        outcome=outcome,
        lesson="Investigate CPU before scaling.",
        metadata={},
    )


def test_basic_decision_requires_review_for_approval_gated_action():
    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(),
        )
    )

    assert result.recommendation == DecisionRecommendation.REVIEW
    assert result.requires_human_review is True


def test_low_risk_non_approval_action_can_proceed():
    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(requires_approval=False),
        )
    )

    assert result.recommendation == DecisionRecommendation.PROCEED
    assert result.requires_human_review is False


def test_high_blast_radius_requires_review():
    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(),
            blast_radius=make_blast_radius(
                score=70,
                risk=RiskLevel.HIGH,
            ),
        )
    )

    assert result.recommendation == DecisionRecommendation.REVIEW
    assert result.risk == RiskLevel.HIGH
    assert result.evidence["impact_score"] == 70


def test_blocked_dependency_blocks_decision():
    dependency = DependencyAction(
        action="investigate_cpu_capacity",
        impact_score=80,
        risk=RiskLevel.CRITICAL,
        blocked=True,
        depends_on=["service-a"],
        reason="High impact dependency",
    )

    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(),
            dependency=dependency,
        )
    )

    assert result.recommendation == DecisionRecommendation.BLOCK
    assert result.risk == RiskLevel.CRITICAL


def test_prediction_can_make_decision_preventive():
    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(requires_approval=False),
            prediction=make_prediction(
                risk=RiskLevel.HIGH,
                signal=PredictionSignal.INCREASING,
            ),
        )
    )

    assert result.preventive is True
    assert result.recommendation == DecisionRecommendation.PROCEED


def test_critical_security_signal_blocks():
    finding = SecurityFinding(
        resource_id="i-123",
        resource_type="ec2",
        finding_type=SecurityFindingType.PUBLIC_ACCESS,
        severity=RiskLevel.CRITICAL,
        description="Critical public access finding",
    )

    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(),
            security_findings=[finding],
        )
    )

    assert result.recommendation == DecisionRecommendation.BLOCK
    assert result.risk == RiskLevel.CRITICAL


def test_high_security_signal_requires_review():
    finding = SecurityFinding(
        resource_id="i-123",
        resource_type="ec2",
        finding_type=SecurityFindingType.MISSING_ENCRYPTION,
        severity=RiskLevel.HIGH,
        description="Encryption is missing",
    )

    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(requires_approval=False),
            security_findings=[finding],
        )
    )

    assert result.recommendation == DecisionRecommendation.REVIEW
    assert result.requires_human_review is True


def test_blocked_simulation_blocks_decision():
    simulation = SimulationResult(
        action_id="action-1",
        outcome=SimulationOutcome.BLOCKED,
        impact_score=90,
        risk=RiskLevel.CRITICAL,
        predicted_status="blocked",
        affected_resources=["i-123"],
        affected_services=["test-service"],
        explanation="Simulation predicts unacceptable impact",
        details={},
    )

    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(),
            simulation=simulation,
        )
    )

    assert result.recommendation == DecisionRecommendation.BLOCK


def test_failed_historical_memory_requires_review():
    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(requires_approval=False),
            memories=[
                make_memory(outcome=MemoryOutcome.FAILURE),
                OperationalMemory(
                    memory_id="memory-2",
                    resource_id="i-123",
                    resource_type="ec2",
                    situation="High CPU utilization detected",
                    action="investigate_cpu_capacity",
                    outcome=MemoryOutcome.FAILURE,
                    lesson="Previous investigation failed.",
                    metadata={},
                ),
            ],
        )
    )

    assert result.recommendation == DecisionRecommendation.REVIEW
    assert result.evidence["historical_failures"] == 2


def test_successful_history_is_exposed():
    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(requires_approval=False),
            memories=[make_memory()],
        )
    )

    assert result.evidence["historical_successes"] == 1
    assert any(
        "successful outcomes" in reason
        for reason in result.reasons
    )


def test_cost_opportunity_is_exposed():
    opportunity = CostOpportunity(
        resource_id="i-123",
        resource_type="ec2",
        signal=CostSignal.UNDERUTILIZED,
        estimated_monthly_savings=30.0,
        confidence="estimated",
        recommendation="Review instance sizing.",
        reason="Low average CPU utilization.",
        details={},
    )

    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(),
            cost_opportunity=opportunity,
        )
    )

    assert result.evidence["estimated_savings"] == 30.0
    assert result.evidence["cost_signal"] == "underutilized"


def test_evidence_contains_prediction_data():
    result = DecisionIntelligenceEngine().evaluate(
        DecisionContext(
            resource_id="i-123",
            resource_type="ec2",
            action=make_action(),
            prediction=make_prediction(
                risk=RiskLevel.MEDIUM,
                signal=PredictionSignal.INCREASING,
            ),
        )
    )

    assert result.evidence["predicted_value"] == 50
    assert result.evidence["prediction_signal"] == "increasing"


def test_resource_mismatch_is_rejected():
    action = ActionPlan(
        action_id="action-1",
        action_type="investigate_cpu_capacity",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-999",
        ),
        reason="CPU issue",
        risk=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ActionStatus.PENDING_APPROVAL,
    )

    try:
        DecisionIntelligenceEngine().evaluate(
            DecisionContext(
                resource_id="i-123",
                resource_type="ec2",
                action=action,
            )
        )
    except ValueError as exc:
        assert "does not match resource_id" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_empty_resource_id_is_rejected():
    try:
        DecisionIntelligenceEngine().evaluate(
            DecisionContext(
                resource_id="",
                resource_type="ec2",
                action=make_action(),
            )
        )
    except ValueError as exc:
        assert str(exc) == "resource_id cannot be empty"
    else:
        raise AssertionError("Expected ValueError")
