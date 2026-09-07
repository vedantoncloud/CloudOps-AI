import pytest

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.executor import ActionExecutor


def create_action(status: ActionStatus) -> ActionPlan:
    action = ActionPlan(
        action_type="stop_instance",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test execution.",
        risk=RiskLevel.MEDIUM,
    )

    action.status = status
    return action


def test_executor_rejects_unapproved_action():
    executor = ActionExecutor()

    action = create_action(ActionStatus.PENDING_APPROVAL)

    with pytest.raises(PermissionError, match="must be approved"):
        executor.execute(action)


def test_executor_rejects_planned_action():
    executor = ActionExecutor()

    action = create_action(ActionStatus.PLANNED)

    with pytest.raises(PermissionError, match="must be approved"):
        executor.execute(action)


def test_executor_does_not_execute_cancelled_action():
    executor = ActionExecutor()

    action = create_action(ActionStatus.CANCELLED)

    with pytest.raises(PermissionError, match="must be approved"):
        executor.execute(action)


def test_approved_action_reaches_execution_boundary():
    executor = ActionExecutor()

    action = create_action(ActionStatus.APPROVED)

    with pytest.raises(
        NotImplementedError,
        match="Infrastructure execution is not implemented",
    ):
        executor.execute(action)

    assert action.status == ActionStatus.EXECUTING


def test_executor_requires_explicit_approval():
    executor = ActionExecutor()

    action = create_action(ActionStatus.PENDING_APPROVAL)

    with pytest.raises(PermissionError):
        executor.execute(action)

    assert action.status == ActionStatus.PENDING_APPROVAL