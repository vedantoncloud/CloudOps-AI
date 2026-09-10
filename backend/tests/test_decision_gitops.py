from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.decision_gitops import DecisionGitOpsBridge
from autonomy.decision_intelligence import (
    DecisionRecommendation,
    DecisionResult,
)
from autonomy.gitops import GitOpsChangeStatus


def make_decision(
    *,
    recommendation=DecisionRecommendation.REVIEW,
    requires_human_review=True,
    risk=RiskLevel.MEDIUM,
):
    action = ActionPlan(
        action_id="action-1",
        action_type="investigate_cpu_capacity",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-123",
        ),
        reason="High CPU utilization detected",
        risk=risk,
        requires_approval=True,
        status=ActionStatus.PENDING_APPROVAL,
    )

    return DecisionResult(
        resource_id="i-123",
        action_id=action.action_id,
        recommendation=recommendation,
        risk=risk,
        confidence=0.85,
        reasons=["Review infrastructure capacity."],
        preventive=False,
        requires_human_review=requires_human_review,
        evidence={
            "impact_score": 70,
        },
    )


def test_review_decision_creates_approval_gated_gitops_proposal():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
        current_value="t3.medium",
    )

    assert result.created is True
    assert result.change_set is not None
    assert result.change_set.status == GitOpsChangeStatus.PENDING_APPROVAL
    assert result.change_set.requires_approval is True


def test_proceed_decision_without_review_creates_direct_dry_run_proposal():
    decision = make_decision(
        recommendation=DecisionRecommendation.PROCEED,
        requires_human_review=False,
        risk=RiskLevel.LOW,
    )

    result = DecisionGitOpsBridge().create_proposal(
        decision,
        field="instance_type",
        desired_value="t3.small",
    )

    assert result.created is True
    assert result.change_set is not None
    assert result.change_set.status == GitOpsChangeStatus.PROPOSED
    assert result.change_set.requires_approval is False


def test_blocked_decision_does_not_create_change():
    decision = make_decision(
        recommendation=DecisionRecommendation.BLOCK,
        risk=RiskLevel.CRITICAL,
    )

    result = DecisionGitOpsBridge().create_proposal(
        decision,
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.created is False
    assert result.change_set is None
    assert "Blocked decision" in result.reason


def test_blocked_result_helper_returns_no_change():
    decision = make_decision(
        recommendation=DecisionRecommendation.BLOCK,
        risk=RiskLevel.CRITICAL,
    )

    result = DecisionGitOpsBridge().create_blocked_result(decision)

    assert result.created is False
    assert result.change_set is None
    assert "blocked" in result.reason.lower()


def test_gitops_change_uses_decision_resource():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="monitoring",
        desired_value=True,
    )

    change = result.change_set.changes[0]

    assert change.resource_id == "i-123"
    assert change.resource_type == "infrastructure"
    assert change.field == "monitoring"
    assert change.desired_value is True


def test_decision_evidence_is_preserved_in_gitops_metadata():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
    )

    metadata = result.change_set.metadata

    assert metadata["decision_recommendation"] == "review"
    assert metadata["decision_risk"] == "medium"
    assert metadata["decision_confidence"] == 0.85
    assert metadata["impact_score"] == 70


def test_decision_reason_is_used_for_gitops_change():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
    )

    change = result.change_set.changes[0]

    assert change.reason == "Review infrastructure capacity."


def test_custom_reason_overrides_decision_reason():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
        reason="Resize based on sustained CPU utilization.",
    )

    change = result.change_set.changes[0]

    assert change.reason == (
        "Resize based on sustained CPU utilization."
    )


def test_custom_metadata_is_preserved():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
        metadata={
            "environment": "production",
            "ticket": "OPS-123",
        },
    )

    metadata = result.change_set.metadata

    assert metadata["environment"] == "production"
    assert metadata["ticket"] == "OPS-123"


def test_empty_field_is_rejected():
    try:
        DecisionGitOpsBridge().create_proposal(
            make_decision(),
            field="",
            desired_value="t3.large",
        )
    except ValueError as exc:
        assert str(exc) == "field cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_review_proposal_can_be_approved_and_dry_run():
    bridge = DecisionGitOpsBridge()

    result = bridge.create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
    )

    change_set = result.change_set

    bridge.engine.approve(change_set, "operator")

    applied = bridge.engine.apply(change_set)

    assert applied.success is True
    assert applied.dry_run is True
    assert change_set.status == GitOpsChangeStatus.APPLIED


def test_blocked_decision_never_reaches_gitops_apply():
    decision = make_decision(
        recommendation=DecisionRecommendation.BLOCK,
        risk=RiskLevel.CRITICAL,
    )

    result = DecisionGitOpsBridge().create_proposal(
        decision,
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.change_set is None


def test_preventive_decision_metadata_is_preserved():
    decision = DecisionResult(
        resource_id="i-123",
        action_id="action-2",
        recommendation=DecisionRecommendation.REVIEW,
        risk=RiskLevel.HIGH,
        confidence=0.80,
        reasons=["Predicted CPU saturation."],
        preventive=True,
        requires_human_review=True,
        evidence={
            "prediction_signal": "increasing",
            "predicted_value": 92,
        },
    )

    result = DecisionGitOpsBridge().create_proposal(
        decision,
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.change_set.metadata["preventive"] is True
    assert result.change_set.metadata["prediction_signal"] == "increasing"
    assert result.change_set.metadata["predicted_value"] == 92


def test_change_set_source_is_decision_action():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.change_set.source_action_id == "action-1"


def test_proposal_is_declarative_and_does_not_mutate_infrastructure():
    result = DecisionGitOpsBridge().create_proposal(
        make_decision(),
        field="instance_type",
        desired_value="t3.large",
        current_value="t3.medium",
    )

    change = result.change_set.changes[0]

    assert change.current_value == "t3.medium"
    assert change.desired_value == "t3.large"
    assert result.created is True


def test_bridge_can_use_injected_gitops_engine():
    from autonomy.gitops import GitOpsEngine

    engine = GitOpsEngine()
    bridge = DecisionGitOpsBridge(engine)

    assert bridge.engine is engine
