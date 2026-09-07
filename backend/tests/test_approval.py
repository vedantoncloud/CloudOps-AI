import pytest

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.approval import ApprovalManager


def create_pending_action() -> ActionPlan:
    action = ActionPlan(
        action_type="stop_instance",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Instance has remained idle.",
        risk=RiskLevel.MEDIUM,
    )

    action.status = ActionStatus.PENDING_APPROVAL
    return action


def test_pending_action_can_be_approved():
    manager = ApprovalManager()

    action = create_pending_action()

    result = manager.approve(action)

    assert result.status == ActionStatus.APPROVED


def test_pending_action_can_be_cancelled():
    manager = ApprovalManager()

    action = create_pending_action()

    result = manager.cancel(action)

    assert result.status == ActionStatus.CANCELLED


def test_approved_action_cannot_be_approved_again():
    manager = ApprovalManager()

    action = create_pending_action()
    manager.approve(action)

    with pytest.raises(
        ValueError,
        match="pending approval",
    ):
        manager.approve(action)


def test_cancelled_action_cannot_be_cancelled_again():
    manager = ApprovalManager()

    action = create_pending_action()
    manager.cancel(action)

    with pytest.raises(
        ValueError,
        match="pending approval",
    ):
        manager.cancel(action)


def test_approved_action_cannot_be_cancelled():
    manager = ApprovalManager()

    action = create_pending_action()
    manager.approve(action)

    with pytest.raises(
        ValueError,
        match="pending approval",
    ):
        manager.cancel(action)


def test_cancelled_action_cannot_be_approved():
    manager = ApprovalManager()

    action = create_pending_action()
    manager.cancel(action)

    with pytest.raises(
        ValueError,
        match="pending approval",
    ):
        manager.approve(action)


def test_planned_action_cannot_be_approved():
    manager = ApprovalManager()

    action = ActionPlan(
        action_type="stop_instance",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test action.",
        risk=RiskLevel.MEDIUM,
    )

    with pytest.raises(
        ValueError,
        match="pending approval",
    ):
        manager.approve(action)


def test_approval_preserves_action_details():
    manager = ApprovalManager()

    action = create_pending_action()

    result = manager.approve(action)

    assert result.action_type == "stop_instance"
    assert result.target.resource_type == "ec2_instance"
    assert result.target.resource_id == "i-123456789"
    assert result.reason == "Instance has remained idle."
    assert result.risk == RiskLevel.MEDIUM