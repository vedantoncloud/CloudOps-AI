from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.control_loop import AutonomousControlLoop
from autonomy.decision_intelligence import (
    DecisionContext,
    DecisionRecommendation,
)
from autonomy.gitops import GitOpsChangeStatus
from autonomy.operational_memory import MemoryOutcome


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


def make_context(action):
    return DecisionContext(
        resource_id=action.target.resource_id,
        resource_type=action.target.resource_type,
        action=action,
    )


def test_control_loop_evaluates_action():
    action = make_action()

    result = AutonomousControlLoop().evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.action is action
    assert result.decision is not None
    assert result.stage_results["action_planned"] is True
    assert result.stage_results["policy_checked"] is True
    assert result.stage_results["decision_evaluated"] is True


def test_control_loop_creates_gitops_proposal():
    action = make_action()

    result = AutonomousControlLoop().evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.gitops is not None
    assert result.gitops.created is True
    assert result.gitops.change_set is not None
    assert (
        result.gitops.change_set.status
        == GitOpsChangeStatus.PENDING_APPROVAL
    )


def test_control_loop_preserves_approval_boundary():
    action = make_action(requires_approval=True)

    result = AutonomousControlLoop().evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.gitops.change_set.requires_approval is True
    assert (
        result.gitops.change_set.status
        == GitOpsChangeStatus.PENDING_APPROVAL
    )


def test_control_loop_never_auto_applies_gitops_change():
    action = make_action()

    result = AutonomousControlLoop().evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.gitops.change_set.status == GitOpsChangeStatus.PENDING_APPROVAL


def test_blocked_decision_does_not_create_change_set():
    action = make_action(
        risk=RiskLevel.CRITICAL,
        requires_approval=True,
    )

    from autonomy.decision_intelligence import DecisionIntelligenceEngine

    class BlockingDecisionEngine(DecisionIntelligenceEngine):
        def evaluate(self, context):
            result = super().evaluate(context)

            from autonomy.decision_intelligence import DecisionResult

            return DecisionResult(
                resource_id=result.resource_id,
                action_id=result.action_id,
                recommendation=DecisionRecommendation.BLOCK,
                risk=RiskLevel.CRITICAL,
                confidence=0.99,
                reasons=["Explicitly blocked for test."],
                preventive=False,
                requires_human_review=True,
                evidence={"test_block": True},
            )

    loop = AutonomousControlLoop(
        decision_engine=BlockingDecisionEngine()
    )

    result = loop.evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    assert result.blocked is True
    assert result.gitops is not None
    assert result.gitops.created is False
    assert result.gitops.change_set is None


def test_control_loop_records_success_in_operational_memory():
    action = make_action()

    loop = AutonomousControlLoop()

    result = loop.evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    action.status = ActionStatus.SUCCEEDED

    result = loop.record_success(
        result,
        lesson="GitOps proposal completed successfully.",
    )

    assert result.memory is not None
    assert result.memory.outcome == MemoryOutcome.SUCCESS
    assert result.stage_results["memory_recorded"] is True


def test_control_loop_records_failure_in_operational_memory():
    action = make_action()

    loop = AutonomousControlLoop()

    result = loop.evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    action.status = ActionStatus.FAILED

    result = loop.record_failure(
        result,
        lesson="Change failed during verification.",
    )

    assert result.memory is not None
    assert result.memory.outcome == MemoryOutcome.FAILURE


def test_control_loop_records_rollback_in_operational_memory():
    action = make_action()

    loop = AutonomousControlLoop()

    result = loop.evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    action.status = ActionStatus.ROLLED_BACK

    result = loop.record_rollback(
        result,
        lesson="Rollback restored the previous state.",
    )

    assert result.memory is not None
    assert result.memory.outcome == MemoryOutcome.ROLLED_BACK


def test_control_loop_preserves_custom_gitops_metadata():
    action = make_action()

    result = AutonomousControlLoop().evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
        gitops_metadata={
            "environment": "production",
            "ticket": "OPS-100",
        },
    )

    assert result.gitops.change_set.metadata["environment"] == "production"
    assert result.gitops.change_set.metadata["ticket"] == "OPS-100"


def test_control_loop_preserves_custom_gitops_reason():
    action = make_action()

    result = AutonomousControlLoop().evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
        gitops_reason="Resize after sustained utilization analysis.",
    )

    change = result.gitops.change_set.changes[0]

    assert change.reason == (
        "Resize after sustained utilization analysis."
    )


def test_mismatched_context_action_is_rejected():
    action = make_action(action_id="action-1")
    other_action = make_action(action_id="action-2")

    try:
        AutonomousControlLoop().evaluate(
            action=action,
            decision_context=make_context(other_action),
            field="instance_type",
            desired_value="t3.large",
        )
    except ValueError as exc:
        assert "does not match supplied action" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_stage_results_capture_decision_recommendation():
    action = make_action(requires_approval=False)

    result = AutonomousControlLoop().evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    assert (
        result.stage_results["decision_recommendation"]
        == result.decision.recommendation.value
    )


def test_memory_recording_does_not_change_blocked_state():
    action = make_action()
    loop = AutonomousControlLoop()

    result = loop.evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    action.status = ActionStatus.SUCCEEDED

    updated = loop.record_success(
        result,
        lesson="Completed safely.",
    )

    assert updated.blocked is False
    assert updated.gitops is result.gitops


def test_control_loop_uses_injected_memory_recorder():
    from autonomy.memory_lifecycle import MemoryLifecycleRecorder
    from autonomy.operational_memory import OperationalMemoryStore

    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    loop = AutonomousControlLoop(
        memory_recorder=recorder,
    )

    action = make_action()

    result = loop.evaluate(
        action=action,
        decision_context=make_context(action),
        field="instance_type",
        desired_value="t3.large",
    )

    action.status = ActionStatus.SUCCEEDED

    loop.record_success(
        result,
        lesson="Test lesson.",
    )

    assert len(store) == 1

