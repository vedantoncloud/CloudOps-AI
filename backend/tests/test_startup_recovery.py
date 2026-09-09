from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.startup_recovery import (
    RecoveryDecision,
    StartupRecoveryManager,
)


def create_action(status: ActionStatus) -> ActionPlan:
    action = ActionPlan(
        action_type="investigate_cpu_capacity",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-startup-test",
        ),
        reason="Test startup recovery",
        risk=RiskLevel.MEDIUM,
        requires_approval=True,
        rollback_available=True,
    )
    action.status = status
    return action


def test_executing_action_requires_startup_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.EXECUTING)
    )

    assert result.action_id.startswith("act-")
    assert result.previous_status == ActionStatus.EXECUTING
    assert result.decision == RecoveryDecision.RECOVERY_REQUIRED
    assert result.details["automatic_execution"] is False


def test_verifying_action_requires_startup_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.VERIFYING)
    )

    assert result.decision == RecoveryDecision.RECOVERY_REQUIRED
    assert result.previous_status == ActionStatus.VERIFYING


def test_rollback_required_action_requires_startup_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.ROLLBACK_REQUIRED)
    )

    assert result.decision == RecoveryDecision.RECOVERY_REQUIRED
    assert result.previous_status == ActionStatus.ROLLBACK_REQUIRED


def test_pending_approval_requires_no_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.PENDING_APPROVAL)
    )

    assert result.decision == RecoveryDecision.NO_ACTION
    assert result.previous_status == ActionStatus.PENDING_APPROVAL


def test_succeeded_action_requires_no_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.SUCCEEDED)
    )

    assert result.decision == RecoveryDecision.NO_ACTION


def test_failed_action_requires_no_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.FAILED)
    )

    assert result.decision == RecoveryDecision.NO_ACTION


def test_cancelled_action_requires_no_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.CANCELLED)
    )

    assert result.decision == RecoveryDecision.NO_ACTION


def test_rolled_back_action_requires_no_recovery():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.ROLLED_BACK)
    )

    assert result.decision == RecoveryDecision.NO_ACTION


def test_startup_recovery_never_allows_automatic_execution():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.EXECUTING)
    )

    assert result.details["automatic_execution"] is False
    assert result.decision == RecoveryDecision.RECOVERY_REQUIRED


def test_inspect_all_returns_result_for_each_action():
    manager = StartupRecoveryManager()

    actions = [
        create_action(ActionStatus.EXECUTING),
        create_action(ActionStatus.SUCCEEDED),
        create_action(ActionStatus.ROLLBACK_REQUIRED),
    ]

    results = manager.inspect_all(actions)

    assert len(results) == 3
    assert results[0].decision == RecoveryDecision.RECOVERY_REQUIRED
    assert results[1].decision == RecoveryDecision.NO_ACTION
    assert results[2].decision == RecoveryDecision.RECOVERY_REQUIRED


def test_recovery_result_contains_resource_context():
    manager = StartupRecoveryManager()

    result = manager.inspect(
        create_action(ActionStatus.VERIFYING)
    )

    assert result.details["action_type"] == "investigate_cpu_capacity"
    assert result.details["resource_type"] == "ec2"
    assert result.details["resource_id"] == "i-startup-test"
