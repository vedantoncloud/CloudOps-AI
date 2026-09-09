import pytest

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.executor import ActionExecutor, ExecutionResult
from autonomy.recovery import RecoveryCoordinator


def create_action(rollback_available: bool = True) -> ActionPlan:
    action = ActionPlan(
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test recovery.",
        risk=RiskLevel.MEDIUM,
        rollback_available=rollback_available,
    )
    action.status = ActionStatus.APPROVED
    return action


def execute(action: ActionPlan) -> ExecutionResult:
    return ActionExecutor().execute(action)


def failed_result(result: ExecutionResult) -> ExecutionResult:
    return ExecutionResult(
        action_id=result.action_id,
        status=result.status,
        dry_run=result.dry_run,
        executed=result.executed,
        successful=False,
        message="Execution failed.",
        details=result.details,
    )


def test_successful_execution_stays_succeeded():
    action = create_action()
    result = execute(action)

    final_action = RecoveryCoordinator().verify_and_recover(action, result)

    assert final_action.status == ActionStatus.SUCCEEDED


def test_failed_execution_with_rollback_is_rolled_back():
    action = create_action(rollback_available=True)
    result = failed_result(execute(action))

    final_action = RecoveryCoordinator().verify_and_recover(action, result)

    assert final_action.status == ActionStatus.ROLLED_BACK


def test_failed_execution_without_rollback_stays_rollback_required():
    action = create_action(rollback_available=False)
    result = failed_result(execute(action))

    final_action = RecoveryCoordinator().verify_and_recover(action, result)

    assert final_action.status == ActionStatus.ROLLBACK_REQUIRED


def test_failed_rollback_marks_action_failed():
    action = create_action(rollback_available=True)
    result = failed_result(execute(action))

    final_action = RecoveryCoordinator().verify_and_recover(
        action,
        result,
        rollback_successful=False,
    )

    assert final_action.status == ActionStatus.FAILED


def test_recovery_rejects_mismatched_execution_result():
    action = create_action()
    result = execute(action)

    mismatched = ExecutionResult(
        action_id="different-action-id",
        status=result.status,
        dry_run=result.dry_run,
        executed=result.executed,
        successful=result.successful,
        message=result.message,
        details=result.details,
    )

    with pytest.raises(ValueError, match="does not match"):
        RecoveryCoordinator().verify_and_recover(action, mismatched)


def test_recovery_does_not_rollback_successful_action():
    action = create_action(rollback_available=True)
    result = execute(action)

    final_action = RecoveryCoordinator().verify_and_recover(action, result)

    assert final_action.status == ActionStatus.SUCCEEDED
    assert final_action.status != ActionStatus.ROLLED_BACK