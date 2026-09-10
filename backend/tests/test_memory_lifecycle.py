from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.memory_lifecycle import MemoryLifecycleRecorder
from autonomy.operational_memory import MemoryOutcome, OperationalMemoryStore


def make_action(
    *,
    action_id="action-1",
    status=ActionStatus.SUCCEEDED,
    action_type="investigate_cpu_capacity",
):
    return ActionPlan(
        action_id=action_id,
        action_type=action_type,
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-123",
        ),
        reason="High CPU utilization detected",
        risk=RiskLevel.MEDIUM,
        requires_approval=True,
        status=status,
    )


def test_successful_action_is_recorded():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    memory = recorder.record_success(
        make_action(),
        lesson="CPU investigation resolved the issue.",
    )

    assert memory.outcome == MemoryOutcome.SUCCESS
    assert memory.resource_id == "i-123"
    assert memory.action == "investigate_cpu_capacity"
    assert len(store) == 1


def test_failed_action_is_recorded():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    memory = recorder.record_failure(
        make_action(status=ActionStatus.FAILED),
        lesson="CPU investigation did not resolve the issue.",
    )

    assert memory.outcome == MemoryOutcome.FAILURE
    assert len(store) == 1


def test_rolled_back_action_is_recorded():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    memory = recorder.record_rollback(
        make_action(status=ActionStatus.ROLLED_BACK),
        lesson="Rollback restored the previous state.",
    )

    assert memory.outcome == MemoryOutcome.ROLLED_BACK


def test_action_context_is_preserved():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    memory = recorder.record_success(
        make_action(),
        lesson="Investigate CPU before scaling.",
        metadata={"impact_score": 40},
    )

    assert memory.metadata["action_id"] == "action-1"
    assert memory.metadata["risk"] == "medium"
    assert memory.metadata["status"] == "succeeded"
    assert memory.metadata["impact_score"] == 40


def test_pending_action_cannot_be_recorded():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    action = make_action(status=ActionStatus.PENDING_APPROVAL)

    try:
        recorder.record_success(
            action,
            lesson="Should not be recorded.",
        )
    except ValueError as exc:
        assert "completed, failed, or rolled-back" in str(exc)
    else:
        raise AssertionError("Expected ValueError")

    assert len(store) == 0


def test_executing_action_cannot_be_recorded():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    action = make_action(status=ActionStatus.EXECUTING)

    try:
        recorder.record_success(
            action,
            lesson="Should not be recorded.",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")


def test_memory_can_be_recalled_for_future_action():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    recorder.record_success(
        make_action(),
        lesson="Investigate CPU before scaling.",
    )

    memories = recorder.recall_for_action(
        resource_type="ec2",
        situation="cpu",
        action_type="investigate_cpu_capacity",
    )

    assert len(memories) == 1
    assert memories[0].lesson == "Investigate CPU before scaling."


def test_lessons_can_be_recalled():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    recorder.record_success(
        make_action(),
        lesson="Investigate CPU before scaling.",
    )

    recorder.record_failure(
        make_action(
            action_id="action-2",
            status=ActionStatus.FAILED,
        ),
        lesson="Check recent CPU trend before retrying.",
    )

    lessons = recorder.lessons_for_action(
        resource_type="ec2",
        situation="CPU",
    )

    assert lessons == [
        "Investigate CPU before scaling.",
        "Check recent CPU trend before retrying.",
    ]


def test_same_action_can_have_multiple_historical_outcomes():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    recorder.record_success(
        make_action(action_id="action-1"),
        lesson="First attempt worked.",
    )

    recorder.record_failure(
        make_action(
            action_id="action-2",
            status=ActionStatus.FAILED,
        ),
        lesson="Second attempt failed.",
    )

    memories = recorder.recall_for_action(
        resource_type="ec2",
        situation="CPU",
        action_type="investigate_cpu_capacity",
    )

    assert len(memories) == 2
    assert memories[0].outcome == MemoryOutcome.SUCCESS
    assert memories[1].outcome == MemoryOutcome.FAILURE


def test_store_is_injected_and_reused():
    store = OperationalMemoryStore()
    recorder = MemoryLifecycleRecorder(store)

    recorder.record_success(
        make_action(),
        lesson="Reusable memory.",
    )

    assert recorder.store is store
    assert len(store) == 1
