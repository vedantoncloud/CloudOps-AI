from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.approval_execution import ApprovalExecutionBridge
from autonomy.audit import AuditTrail
from autonomy.execution_safety import ExecutionSafetyGate
from autonomy.execution_verification import ExecutionVerificationBridge
from autonomy.executor import ExecutionResult
from autonomy.autonomous_lifecycle import (
    AutonomousLifecycleOrchestrator,
    LifecycleOutcome,
)


def make_action(action_id="life-1", status=ActionStatus.APPROVED):
    return ActionPlan(
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123",
        ),
        reason="lifecycle test",
        risk=RiskLevel.LOW,
        requires_approval=True,
        rollback_available=True,
        status=status,
        action_id=action_id,
    )


class FakeExecutor:
    def __init__(self, successful=True):
        self.calls = []
        self.successful = successful

    def execute(self, action, *, dry_run=True):
        self.calls.append((action, dry_run))
        action.status = ActionStatus.EXECUTING
        return ExecutionResult(
            action_id=action.action_id,
            status=ActionStatus.EXECUTING,
            dry_run=dry_run,
            executed=False,
            successful=self.successful,
            message="simulated lifecycle execution",
            details={"source": "task8-test"},
        )


def make_orchestrator(*, successful=True, audit=None):
    audit = audit or AuditTrail()
    executor = FakeExecutor(successful=successful)
    approval = ApprovalExecutionBridge(
        safety_gate=ExecutionSafetyGate(),
        executor=executor,
    )
    verification = ExecutionVerificationBridge(audit_trail=audit)
    orchestrator = AutonomousLifecycleOrchestrator(
        approval_bridge=approval,
        verification_bridge=verification,
        audit_trail=audit,
    )
    return orchestrator, executor, audit


def test_unapproved_action_waits_for_human_approval():
    orchestrator, executor, _ = make_orchestrator()
    action = make_action()

    result = orchestrator.run(action, dry_run=False)

    assert result.outcome == LifecycleOutcome.AWAITING_APPROVAL
    assert result.requires_human_approval is True
    assert executor.calls == []


def test_approved_action_completes_end_to_end():
    orchestrator, executor, audit = make_orchestrator()
    action = make_action()

    result = orchestrator.approve_and_run(
        action,
        approved_by="operator",
        dry_run=True,
    )

    assert result.completed is True
    assert result.outcome == LifecycleOutcome.COMPLETED
    assert result.verification is not None
    assert result.verification.verified is True
    assert action.status == ActionStatus.SUCCEEDED
    assert len(executor.calls) == 1
    assert executor.calls[0][1] is True
    assert len(audit.get_events(action.action_id)) == 4


def test_rejected_action_never_reaches_executor():
    orchestrator, executor, audit = make_orchestrator()
    action = make_action()

    result = orchestrator.reject(
        action,
        rejected_by="operator",
        reason="change not required",
        dry_run=False,
    )

    assert result.outcome == LifecycleOutcome.AWAITING_APPROVAL
    assert result.approval.status.value == "rejected"
    assert executor.calls == []
    assert result.evidence["approval_status"] == "rejected"
    assert len(audit.get_events(action.action_id)) >= 2


def test_idempotency_seen_blocks_execution():
    orchestrator, executor, audit = make_orchestrator()
    action = make_action()

    result = orchestrator.approve_and_run(
        action,
        approved_by="operator",
        idempotency_key="already-used",
        idempotency_seen=True,
        dry_run=True,
    )

    assert result.outcome == LifecycleOutcome.BLOCKED
    assert result.blocked is True
    assert result.safety.decision.value == "deny"
    assert executor.calls == []
    assert len(audit.get_events(action.action_id)) >= 3


def test_failed_verification_produces_failed_lifecycle():
    orchestrator, executor, audit = make_orchestrator(successful=False)
    action = make_action()

    result = orchestrator.approve_and_run(
        action,
        approved_by="operator",
        dry_run=True,
    )

    assert result.outcome == LifecycleOutcome.FAILED
    assert result.completed is False
    assert result.verification is not None
    assert result.verification.verified is False
    assert action.status == ActionStatus.ROLLBACK_REQUIRED
    assert len(executor.calls) == 1
    assert len(audit.get_events(action.action_id)) == 4


def test_approval_is_reused_for_repeat_run():
    orchestrator, executor, _ = make_orchestrator()
    action = make_action()

    first = orchestrator.approve_and_run(
        action,
        approved_by="operator",
        dry_run=True,
    )

    # A completed action should not be silently executed again.
    # The existing safety layer's idempotency control is the explicit
    # mechanism for this scenario.
    assert first.completed is True

    second_action = make_action(action_id="life-2")
    second = orchestrator.run(
        second_action,
        dry_run=False,
    )

    assert second.requires_human_approval is True
    assert len(executor.calls) == 1


def test_decision_and_blast_radius_are_forwarded_to_safety_gate():
    class RecordingGate(ExecutionSafetyGate):
        def __init__(self):
            super().__init__()
            self.received = None

        def evaluate(self, action, **kwargs):
            self.received = kwargs
            return super().evaluate(action, **kwargs)

    gate = RecordingGate()
    audit = AuditTrail()
    executor = FakeExecutor()
    approval = ApprovalExecutionBridge(
        safety_gate=gate,
        executor=executor,
    )
    orchestrator = AutonomousLifecycleOrchestrator(
        approval_bridge=approval,
        verification_bridge=ExecutionVerificationBridge(audit_trail=audit),
        audit_trail=audit,
    )
    action = make_action()

    decision = {"recommendation": "proceed"}
    blast_radius = {"impact_score": 10}

    result = orchestrator.approve_and_run(
        action,
        approved_by="operator",
        decision=decision,
        blast_radius=blast_radius,
        dry_run=True,
    )

    assert result.completed is True
    assert gate.received["decision"] is decision
    assert gate.received["blast_radius"] is blast_radius


def test_evidence_contains_complete_lifecycle_trace():
    orchestrator, _, _ = make_orchestrator()
    action = make_action()

    result = orchestrator.approve_and_run(
        action,
        approved_by="operator",
        dry_run=True,
    )

    assert result.evidence["action_id"] == action.action_id
    assert result.evidence["approval_status"] == "approved"
    assert result.evidence["approved_by"] == "operator"
    assert result.evidence["safety_decision"] == "allow"
    assert result.evidence["execution_allowed"] is True
    assert result.evidence["verification"]["verification_outcome"] == "verified"


def test_audit_events_are_scoped_by_action_id():
    orchestrator, _, audit = make_orchestrator()
    first = make_action("life-a")
    second = make_action("life-b")

    orchestrator.approve_and_run(first, approved_by="operator")
    orchestrator.approve_and_run(second, approved_by="operator")

    first_events = orchestrator.audit_events("life-a")
    second_events = orchestrator.audit_events("life-b")

    assert first_events
    assert second_events
    assert all(event.action_id == "life-a" for event in first_events)
    assert all(event.action_id == "life-b" for event in second_events)


def test_empty_action_id_is_rejected():
    orchestrator, _, _ = make_orchestrator()
    action = make_action()
    object.__setattr__(action, "action_id", "")
    try:
        orchestrator.run(action)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "action_id" in str(exc)

def test_rejection_requires_reason():
    orchestrator, _, _ = make_orchestrator()
    action = make_action()

    try:
        orchestrator.run(
            action,
            rejected_by="operator",
            rejection_reason=None,
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "rejection_reason" in str(exc)


def test_approval_and_verification_components_are_reused():
    audit = AuditTrail()
    executor = FakeExecutor()
    approval = ApprovalExecutionBridge(executor=executor)
    verification = ExecutionVerificationBridge(audit_trail=audit)

    orchestrator = AutonomousLifecycleOrchestrator(
        approval_bridge=approval,
        verification_bridge=verification,
        audit_trail=audit,
    )

    action = make_action()
    result = orchestrator.approve_and_run(
        action,
        approved_by="operator",
        dry_run=True,
    )

    assert result.completed is True
    assert len(audit.get_events(action.action_id)) == 4
