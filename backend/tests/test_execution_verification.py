from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.audit import AuditTrail
from autonomy.executor import ExecutionResult
from autonomy.verifier import ActionVerifier
from autonomy.execution_verification import (
    ExecutionVerificationBridge,
    VerificationOutcome,
)


def make_action(
    *,
    action_id="act-verify-1",
    status=ActionStatus.APPROVED,
    action_type="review_instance_state",
):
    return ActionPlan(
        action_type=action_type,
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123",
        ),
        reason="verification test",
        risk=RiskLevel.LOW,
        requires_approval=True,
        rollback_available=True,
        status=status,
        action_id=action_id,
    )


class FakeExecutor:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def execute(self, action, *, dry_run=True):
        self.calls.append((action, dry_run))
        if self.result is not None:
            action.status = ActionStatus.EXECUTING
            return self.result
        action.status = ActionStatus.EXECUTING
        return ExecutionResult(
            action_id=action.action_id,
            status=ActionStatus.EXECUTING,
            dry_run=dry_run,
            executed=False,
            successful=True,
            message="fake execution",
            details={"source": "test"},
        )


class FakeVerifier(ActionVerifier):
    pass


def test_execute_and_verify_success():
    audit = AuditTrail()
    executor = FakeExecutor()
    bridge = ExecutionVerificationBridge(
        executor=executor,
        audit_trail=audit,
    )
    action = make_action()

    result = bridge.execute_and_verify(action)

    assert result.verified is True
    assert result.successful is True
    assert result.verification_outcome == VerificationOutcome.VERIFIED
    assert result.new_status == ActionStatus.SUCCEEDED.value
    assert action.status == ActionStatus.SUCCEEDED
    assert len(executor.calls) == 1


def test_execute_and_verify_records_execution_and_verification_audit():
    audit = AuditTrail()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(),
        audit_trail=audit,
    )
    action = make_action()

    result = bridge.execute_and_verify(action)
    events = audit.get_events(action.action_id)

    assert result.audit_event_count == 2
    assert len(events) == 2
    assert events[0].event == "action_execution_completed"
    assert events[1].event == "action_verification_completed"
    assert events[0].old_status == ActionStatus.APPROVED.value
    assert events[0].new_status == ActionStatus.EXECUTING.value
    assert events[1].old_status == ActionStatus.EXECUTING.value
    assert events[1].new_status == ActionStatus.SUCCEEDED.value


def test_failed_execution_result_requires_rollback():
    audit = AuditTrail()
    failed = ExecutionResult(
        action_id="act-verify-1",
        status=ActionStatus.EXECUTING,
        dry_run=True,
        executed=False,
        successful=False,
        message="simulated failure",
        details={"error": "verification mismatch"},
    )
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(result=failed),
        audit_trail=audit,
    )
    action = make_action()

    result = bridge.execute_and_verify(action)

    assert result.verified is False
    assert result.successful is False
    assert result.requires_rollback is True
    assert result.verification_outcome == VerificationOutcome.FAILED
    assert action.status == ActionStatus.ROLLBACK_REQUIRED


def test_failed_verification_is_audited():
    audit = AuditTrail()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(),
        audit_trail=audit,
    )
    action = make_action()

    bridge.execute_and_verify(action)

    events = audit.get_events(action.action_id)
    verification = events[-1]

    assert verification.event == "action_verification_completed"
    assert verification.new_status == ActionStatus.SUCCEEDED.value
    assert verification.details["verification_outcome"] == VerificationOutcome.VERIFIED


def test_mismatched_execution_result_is_rejected():
    audit = AuditTrail()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(),
        audit_trail=audit,
    )
    action = make_action()

    result = ExecutionResult(
        action_id="different-action",
        status=ActionStatus.EXECUTING,
        dry_run=True,
        executed=False,
        successful=True,
        message="mismatch",
        details={},
    )

    try:
        bridge.verify(action, result)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "does not match" in str(exc)


def test_non_executing_action_cannot_be_verified():
    bridge = ExecutionVerificationBridge(audit_trail=AuditTrail())
    action = make_action(status=ActionStatus.APPROVED)

    result = ExecutionResult(
        action_id=action.action_id,
        status=ActionStatus.EXECUTING,
        dry_run=True,
        executed=False,
        successful=True,
        message="test",
        details={},
    )

    try:
        bridge.verify(action, result)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "must be executing" in str(exc)


def test_non_approved_action_cannot_execute():
    executor = FakeExecutor()
    bridge = ExecutionVerificationBridge(executor=executor)
    action = make_action(status=ActionStatus.PENDING_APPROVAL)

    try:
        bridge.execute_and_verify(action)
        assert False, "Expected PermissionError"
    except PermissionError as exc:
        assert "approved" in str(exc).lower()

    assert executor.calls == []


def test_execution_hook_runs_before_verification():
    observed = []
    bridge = ExecutionVerificationBridge(executor=FakeExecutor())
    action = make_action()

    def hook(current_action, execution_result):
        observed.append(
            (
                current_action.status,
                execution_result.action_id,
                execution_result.successful,
            )
        )

    bridge.execute_and_verify(action, execution_hook=hook)

    assert observed == [
        (ActionStatus.EXECUTING, action.action_id, True)
    ]


def test_verification_details_are_preserved_in_audit():
    audit = AuditTrail()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(),
        audit_trail=audit,
    )
    action = make_action()

    bridge.execute_and_verify(
        action,
        verification_details={
            "observed_state": "running",
            "expected_state": "running",
        },
    )

    event = audit.get_events(action.action_id)[-1]

    assert event.details["observed_state"] == "running"
    assert event.details["expected_state"] == "running"


def test_result_contains_lifecycle_evidence():
    audit = AuditTrail()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(),
        audit_trail=audit,
    )
    action = make_action()

    result = bridge.execute_and_verify(action)

    assert result.evidence["action_id"] == action.action_id
    assert result.evidence["execution_status"] == ActionStatus.EXECUTING.value
    assert result.evidence["verification_status"] == ActionStatus.SUCCEEDED.value
    assert result.evidence["audit_event_count"] == 2


def test_custom_verifier_can_be_injected():
    audit = AuditTrail()
    verifier = ActionVerifier()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(),
        verifier=verifier,
        audit_trail=audit,
    )
    action = make_action()

    result = bridge.execute_and_verify(action)

    assert result.verified is True
    assert result.new_status == ActionStatus.SUCCEEDED.value


def test_custom_audit_trail_is_reused():
    audit = AuditTrail()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(),
        audit_trail=audit,
    )
    action = make_action()

    result = bridge.execute_and_verify(action)

    assert result.audit_event_count == len(audit.get_events(action.action_id))


def test_mismatched_execution_result_creates_no_audit_event():
    audit = AuditTrail()
    bridge = ExecutionVerificationBridge(
        executor=FakeExecutor(
            result=ExecutionResult(
                action_id="different-action",
                status=ActionStatus.EXECUTING,
                dry_run=True,
                executed=False,
                successful=True,
                message="mismatch",
                details={},
            )
        ),
        audit_trail=audit,
    )
    action = make_action()

    try:
        bridge.execute_and_verify(action)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "does not match" in str(exc)

    assert audit.get_events(action.action_id) == []
