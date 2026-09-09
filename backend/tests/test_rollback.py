import pytest

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.rollback import RollbackManager


def create_rollback_action(
    *,
    status: ActionStatus = ActionStatus.ROLLBACK_REQUIRED,
    rollback_available: bool = True,
) -> ActionPlan:
    action = ActionPlan(
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test rollback.",
        risk=RiskLevel.MEDIUM,
        rollback_available=rollback_available,
    )
    action.status = status
    return action


def test_successful_rollback_marks_action_rolled_back():
    action = create_rollback_action()

    result = RollbackManager().rollback(action)

    assert result.action_id == action.action_id
    assert result.status == ActionStatus.ROLLED_BACK
    assert result.rolled_back is False
    assert "no infrastructure mutation" in result.message
    assert action.status == ActionStatus.ROLLED_BACK


def test_failed_rollback_marks_action_failed():
    action = create_rollback_action()

    result = RollbackManager().rollback(
        action,
        successful=False,
    )

    assert result.status == ActionStatus.FAILED
    assert result.rolled_back is False
    assert action.status == ActionStatus.FAILED


def test_rollback_requires_rollback_required_status():
    action = create_rollback_action(
        status=ActionStatus.EXECUTING,
    )

    with pytest.raises(
        ValueError,
        match="must require rollback",
    ):
        RollbackManager().rollback(action)

    assert action.status == ActionStatus.EXECUTING


def test_rollback_requires_rollback_availability():
    action = create_rollback_action(
        rollback_available=False,
    )

    with pytest.raises(
        ValueError,
        match="Rollback is not available",
    ):
        RollbackManager().rollback(action)

    assert action.status == ActionStatus.ROLLBACK_REQUIRED


def test_rollback_rejects_succeeded_action():
    action = create_rollback_action(
        status=ActionStatus.SUCCEEDED,
    )

    with pytest.raises(
        ValueError,
        match="must require rollback",
    ):
        RollbackManager().rollback(action)


def test_rollback_result_preserves_action_identity():
    action = create_rollback_action()

    result = RollbackManager().rollback(action)

    assert result.action_id == action.action_id
    assert result.details["action_type"] == action.action_type
    assert result.details["resource_type"] == action.target.resource_type
    assert result.details["resource_id"] == action.target.resource_id
