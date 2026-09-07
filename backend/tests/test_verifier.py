import pytest

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.verifier import ActionVerifier


def create_executing_action() -> ActionPlan:
    action = ActionPlan(
        action_type="stop_instance",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test verification.",
        risk=RiskLevel.MEDIUM,
    )

    action.status = ActionStatus.EXECUTING
    return action


def test_successful_action_is_marked_succeeded():
    verifier = ActionVerifier()

    action = create_executing_action()

    result = verifier.verify(
        action,
        successful=True,
    )

    assert result.status == ActionStatus.SUCCEEDED


def test_failed_action_requires_rollback():
    verifier = ActionVerifier()

    action = create_executing_action()

    result = verifier.verify(
        action,
        successful=False,
    )

    assert result.status == ActionStatus.ROLLBACK_REQUIRED


def test_verifier_preserves_action_details():
    verifier = ActionVerifier()

    action = create_executing_action()

    result = verifier.verify(
        action,
        successful=True,
    )

    assert result.action_type == "stop_instance"
    assert result.target.resource_type == "ec2_instance"
    assert result.target.resource_id == "i-123456789"
    assert result.reason == "Test verification."
    assert result.risk == RiskLevel.MEDIUM


def test_verifier_rejects_unexecuted_action():
    verifier = ActionVerifier()

    action = ActionPlan(
        action_type="stop_instance",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test verification.",
        risk=RiskLevel.MEDIUM,
    )

    with pytest.raises(
        ValueError,
        match="must be executing",
    ):
        verifier.verify(
            action,
            successful=True,
        )


def test_verifier_rejects_approved_action():
    verifier = ActionVerifier()

    action = create_executing_action()
    action.status = ActionStatus.APPROVED

    with pytest.raises(
        ValueError,
        match="must be executing",
    ):
        verifier.verify(
            action,
            successful=True,
        )


def test_failed_verification_does_not_mark_action_succeeded():
    verifier = ActionVerifier()

    action = create_executing_action()

    result = verifier.verify(
        action,
        successful=False,
    )

    assert result.status != ActionStatus.SUCCEEDED
    assert result.status == ActionStatus.ROLLBACK_REQUIRED