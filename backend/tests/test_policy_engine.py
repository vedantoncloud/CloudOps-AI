from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.policy_engine import PolicyEngine


def create_action(risk: RiskLevel) -> ActionPlan:
    return ActionPlan(
        action_type="stop_instance",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Test action.",
        risk=risk,
    )


def test_low_risk_action_requires_approval():
    engine = PolicyEngine()

    action = create_action(RiskLevel.LOW)
    result = engine.evaluate(action)

    assert result.requires_approval is True
    assert result.status == ActionStatus.PENDING_APPROVAL


def test_medium_risk_action_requires_approval():
    engine = PolicyEngine()

    action = create_action(RiskLevel.MEDIUM)
    result = engine.evaluate(action)

    assert result.requires_approval is True
    assert result.status == ActionStatus.PENDING_APPROVAL


def test_high_risk_action_requires_approval():
    engine = PolicyEngine()

    action = create_action(RiskLevel.HIGH)
    result = engine.evaluate(action)

    assert result.requires_approval is True
    assert result.status == ActionStatus.PENDING_APPROVAL


def test_critical_risk_action_requires_approval():
    engine = PolicyEngine()

    action = create_action(RiskLevel.CRITICAL)
    result = engine.evaluate(action)

    assert result.requires_approval is True
    assert result.status == ActionStatus.PENDING_APPROVAL


def test_policy_engine_preserves_action_details():
    engine = PolicyEngine()

    action = create_action(RiskLevel.HIGH)
    result = engine.evaluate(action)

    assert result.action_type == "stop_instance"
    assert result.target.resource_id == "i-123456789"
    assert result.reason == "Test action."
    assert result.risk == RiskLevel.HIGH


def test_policy_engine_does_not_execute_action():
    engine = PolicyEngine()

    action = create_action(RiskLevel.LOW)
    result = engine.evaluate(action)

    # Policy evaluation must never execute the action.
    assert result.status != ActionStatus.EXECUTING
    assert result.status == ActionStatus.PENDING_APPROVAL