import pytest

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.executor import ActionExecutor, ExecutionResult
from autonomy.verifier import ActionVerifier


def create_approved_action() -> ActionPlan:
    action = ActionPlan(
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test verification.",
        risk=RiskLevel.MEDIUM,
    )

    action.status = ActionStatus.APPROVED
    return action


def execute_action(action: ActionPlan) -> ExecutionResult:
    return ActionExecutor().execute(action)


def test_successful_execution_is_marked_succeeded():
    action = create_approved_action()
    execution_result = execute_action(action)

    result = ActionVerifier().verify(action, execution_result)

    assert result.status == ActionStatus.SUCCEEDED


def test_failed_execution_requires_rollback():
    action = create_approved_action()
    execution_result = execute_action(action)

    failed_result = ExecutionResult(
        action_id=execution_result.action_id,
        status=execution_result.status,
        dry_run=execution_result.dry_run,
        executed=execution_result.executed,
        successful=False,
        message="Execution failed.",
        details=execution_result.details,
    )

    result = ActionVerifier().verify(action, failed_result)

    assert result.status == ActionStatus.ROLLBACK_REQUIRED


def test_verifier_rejects_result_for_different_action():
    action = create_approved_action()
    execution_result = execute_action(action)

    mismatched_result = ExecutionResult(
        action_id="different-action-id",
        status=execution_result.status,
        dry_run=execution_result.dry_run,
        executed=execution_result.executed,
        successful=True,
        message=execution_result.message,
        details=execution_result.details,
    )

    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        ActionVerifier().verify(action, mismatched_result)


def test_verifier_rejects_non_executing_action():
    action = create_approved_action()
    execution_result = execute_action(action)

    action.status = ActionStatus.APPROVED

    with pytest.raises(
        ValueError,
        match="must be executing",
    ):
        ActionVerifier().verify(action, execution_result)


def test_verifier_rejects_invalid_execution_result_status():
    action = create_approved_action()
    execution_result = execute_action(action)

    invalid_result = ExecutionResult(
        action_id=execution_result.action_id,
        status=ActionStatus.APPROVED,
        dry_run=execution_result.dry_run,
        executed=execution_result.executed,
        successful=True,
        message=execution_result.message,
        details=execution_result.details,
    )

    with pytest.raises(
        ValueError,
        match="must represent an executing",
    ):
        ActionVerifier().verify(action, invalid_result)


def test_failed_verification_does_not_mark_action_succeeded():
    action = create_approved_action()
    execution_result = execute_action(action)

    failed_result = ExecutionResult(
        action_id=execution_result.action_id,
        status=execution_result.status,
        dry_run=execution_result.dry_run,
        executed=execution_result.executed,
        successful=False,
        message="Execution failed.",
        details=execution_result.details,
    )

    result = ActionVerifier().verify(action, failed_result)

    assert result.status != ActionStatus.SUCCEEDED
    assert result.status == ActionStatus.ROLLBACK_REQUIRED