from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.idempotency import IdempotencyManager


def create_action(status=ActionStatus.APPROVED):
    action = ActionPlan(
        action_type="investigate_cpu_capacity",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-idempotency-test",
        ),
        reason="Test idempotent execution",
        risk=RiskLevel.LOW,
        requires_approval=True,
        rollback_available=True,
    )
    action.status = status
    return action


def test_first_execution_creates_execution_record():
    manager = IdempotencyManager()
    action = create_action()

    record = manager.start_execution(action)

    assert record.action_id == action.action_id
    assert record.execution_id.startswith("exec-")
    assert record.status == ActionStatus.EXECUTING


def test_second_execution_is_rejected():
    manager = IdempotencyManager()
    action = create_action()

    first = manager.start_execution(action)

    try:
        manager.start_execution(action)
        assert False
    except ValueError as exc:
        assert first.execution_id in str(exc)


def test_execution_id_is_unique():
    manager = IdempotencyManager()

    action_one = create_action()
    action_two = create_action()

    first = manager.start_execution(action_one)
    second = manager.start_execution(action_two)

    assert first.execution_id != second.execution_id


def test_get_execution_returns_record():
    manager = IdempotencyManager()
    action = create_action()

    created = manager.start_execution(action)
    result = manager.get_execution(action.action_id)

    assert result is not None
    assert result.execution_id == created.execution_id
    assert result.status == ActionStatus.EXECUTING


def test_missing_execution_returns_none():
    manager = IdempotencyManager()

    assert manager.get_execution("act-missing") is None


def test_has_execution():
    manager = IdempotencyManager()
    action = create_action()

    assert manager.has_execution(action.action_id) is False

    manager.start_execution(action)

    assert manager.has_execution(action.action_id) is True


def test_succeeded_action_cannot_start_execution():
    manager = IdempotencyManager()
    action = create_action(ActionStatus.SUCCEEDED)

    try:
        manager.start_execution(action)
        assert False
    except ValueError as exc:
        assert "succeeded" in str(exc)


def test_executing_action_cannot_start_execution():
    manager = IdempotencyManager()
    action = create_action(ActionStatus.EXECUTING)

    try:
        manager.start_execution(action)
        assert False
    except ValueError as exc:
        assert "executing" in str(exc)


def test_rollback_required_action_cannot_start_execution():
    manager = IdempotencyManager()
    action = create_action(ActionStatus.ROLLBACK_REQUIRED)

    try:
        manager.start_execution(action)
        assert False
    except ValueError as exc:
        assert "rollback_required" in str(exc)


def test_complete_execution_preserves_execution_id():
    manager = IdempotencyManager()
    action = create_action()

    created = manager.start_execution(action)

    action.status = ActionStatus.SUCCEEDED

    completed = manager.complete_execution(action)

    assert completed.execution_id == created.execution_id
    assert completed.status == ActionStatus.SUCCEEDED


def test_complete_without_execution_is_rejected():
    manager = IdempotencyManager()
    action = create_action()

    try:
        manager.complete_execution(action)
        assert False
    except ValueError as exc:
        assert "No execution attempt exists" in str(exc)


def test_clear_removes_execution_record():
    manager = IdempotencyManager()
    action = create_action()

    manager.start_execution(action)

    assert manager.has_execution(action.action_id) is True

    manager.clear(action.action_id)

    assert manager.has_execution(action.action_id) is False
