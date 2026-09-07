import pytest

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)


def test_action_target_creation():
    target = ActionTarget(
        resource_type="ec2_instance",
        resource_id="i-123456789",
    )

    assert target.resource_type == "ec2_instance"
    assert target.resource_id == "i-123456789"
    assert target.metadata == {}


def test_action_target_supports_metadata():
    target = ActionTarget(
        resource_type="ec2_instance",
        resource_id="i-123456789",
        metadata={"region": "ap-south-1"},
    )

    assert target.metadata["region"] == "ap-south-1"


def test_action_plan_creation():
    target = ActionTarget(
        resource_type="ec2_instance",
        resource_id="i-123456789",
    )

    plan = ActionPlan(
        action_type="stop_instance",
        target=target,
        reason="Instance has been idle for an extended period.",
        risk=RiskLevel.MEDIUM,
    )

    assert plan.action_type == "stop_instance"
    assert plan.target == target
    assert plan.risk == RiskLevel.MEDIUM
    assert plan.requires_approval is True
    assert plan.status == ActionStatus.PLANNED
    assert plan.action_id.startswith("act-")


def test_each_action_plan_gets_unique_id():
    target = ActionTarget(
        resource_type="ec2_instance",
        resource_id="i-123456789",
    )

    plan_one = ActionPlan(
        action_type="stop_instance",
        target=target,
        reason="Idle instance.",
        risk=RiskLevel.MEDIUM,
    )

    plan_two = ActionPlan(
        action_type="stop_instance",
        target=target,
        reason="Idle instance.",
        risk=RiskLevel.MEDIUM,
    )

    assert plan_one.action_id != plan_two.action_id


def test_critical_action_requires_approval():
    target = ActionTarget(
        resource_type="ec2_instance",
        resource_id="i-123456789",
    )

    with pytest.raises(ValueError):
        ActionPlan(
            action_type="terminate_instance",
            target=target,
            reason="Instance must be removed.",
            risk=RiskLevel.CRITICAL,
            requires_approval=False,
        )


def test_empty_resource_type_is_rejected():
    with pytest.raises(ValueError):
        ActionTarget(
            resource_type="",
            resource_id="i-123456789",
        )


def test_empty_resource_id_is_rejected():
    with pytest.raises(ValueError):
        ActionTarget(
            resource_type="ec2_instance",
            resource_id="",
        )


def test_empty_action_type_is_rejected():
    target = ActionTarget(
        resource_type="ec2_instance",
        resource_id="i-123456789",
    )

    with pytest.raises(ValueError):
        ActionPlan(
            action_type="",
            target=target,
            reason="Test action.",
            risk=RiskLevel.LOW,
        )


def test_empty_reason_is_rejected():
    target = ActionTarget(
        resource_type="ec2_instance",
        resource_id="i-123456789",
    )

    with pytest.raises(ValueError):
        ActionPlan(
            action_type="stop_instance",
            target=target,
            reason="",
            risk=RiskLevel.LOW,
        )