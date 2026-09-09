import pytest

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.executor import ActionExecutor


def create_action(action_type="review_instance_state", status=ActionStatus.APPROVED):
    action = ActionPlan(
        action_type=action_type,
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
    with pytest.raises(PermissionError, match="must be approved"):
        ActionExecutor().execute(create_action(status=ActionStatus.PENDING_APPROVAL))


def test_executor_rejects_planned_action():
    with pytest.raises(PermissionError, match="must be approved"):
        ActionExecutor().execute(create_action(status=ActionStatus.PLANNED))


def test_executor_rejects_non_allowlisted_action():
    with pytest.raises(ValueError, match="not allowlisted"):
        ActionExecutor().execute(create_action(action_type="stop_instance"))


def test_executor_dry_run_does_not_mutate_infrastructure():
    action = create_action()
    result = ActionExecutor().execute(action)

    assert result.dry_run is True
    assert result.executed is False
    assert result.successful is True
    assert result.status == ActionStatus.EXECUTING
    assert action.status == ActionStatus.EXECUTING
    assert "no infrastructure mutation" in result.message


def test_executor_real_mode_is_disabled():
    action = create_action()

    with pytest.raises(
        NotImplementedError,
        match="Real infrastructure execution is disabled",
    ):
        ActionExecutor().execute(action, dry_run=False)


def test_executor_requires_explicit_approval():
    action = create_action(status=ActionStatus.CANCELLED)

    with pytest.raises(PermissionError):
        ActionExecutor().execute(action)

    assert action.status == ActionStatus.CANCELLED
