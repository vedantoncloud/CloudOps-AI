from dataclasses import dataclass, field
from enum import Enum

from autonomy.action_models import ActionStatus
from autonomy.approval_execution import (
    ApprovalExecutionBridge,
    ApprovalStatus,
)
from autonomy.execution_safety import ExecutionSafetyDecision


class Status(str, Enum):
    PLANNED = "planned"
    APPROVED = "approved"


@dataclass
class Target:
    resource_id: str = "i-123"


@dataclass
class Action:
    action_id: str = "act-1"
    action_type: str = "scale"
    target: Target = field(default_factory=Target)
    rationale: str = "test action"
    status: ActionStatus = ActionStatus.PENDING_APPROVAL


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, action, *, dry_run=True):
        self.calls.append((action, dry_run))
        return {
            "action_id": action.action_id,
            "executed": True,
            "dry_run": dry_run,
        }


def test_submit_creates_pending_approval():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    result = bridge.submit(action)

    assert result.action_id == "act-1"
    assert result.status is ApprovalStatus.PENDING
    assert result.approved_by is None


def test_submit_is_idempotent_for_same_action():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    first = bridge.submit(action)
    second = bridge.submit(action)

    assert first == second


def test_get_returns_approval_record():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    bridge.submit(action)

    record = bridge.get("act-1")

    assert record is not None
    assert record.action_id == "act-1"
    assert record.status is ApprovalStatus.PENDING


def test_approve_marks_action_approved():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    record = bridge.approve(action, approved_by="operator")

    assert record.status is ApprovalStatus.APPROVED
    assert record.approved_by == "operator"


def test_approve_is_idempotent():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    first = bridge.approve(action, approved_by="operator")
    second = bridge.approve(action, approved_by="operator")

    assert first == second


def test_reject_marks_action_rejected():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    record = bridge.reject(
        action,
        rejected_by="operator",
        reason="unsafe change",
    )

    assert record.status is ApprovalStatus.REJECTED
    assert record.rejection_reason == "unsafe change"


def test_rejected_action_cannot_be_reapproved():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    bridge.reject(
        action,
        rejected_by="operator",
        reason="unsafe change",
    )

    try:
        bridge.approve(action, approved_by="operator")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_approved_action_cannot_be_rejected():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    bridge.approve(action, approved_by="operator")

    try:
        bridge.reject(
            action,
            rejected_by="operator",
            reason="changed mind",
        )
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_dry_run_can_execute_without_human_approval():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    result = bridge.execute(action, dry_run=True)

    assert result.safety.decision is ExecutionSafetyDecision.ALLOW
    assert result.executed is True
    assert len(executor.calls) == 1
    assert executor.calls[0][1] is True


def test_pending_non_dry_run_requires_approval():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    result = bridge.execute(action, dry_run=False)

    assert result.safety.decision is ExecutionSafetyDecision.REVIEW
    assert result.requires_human_approval is True
    assert result.executed is False
    assert len(executor.calls) == 0


def test_rejected_action_never_reaches_executor():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    bridge.reject(
        action,
        rejected_by="operator",
        reason="not allowed",
    )

    result = bridge.execute(action, dry_run=False)

    assert result.executed is False
    assert result.safety.decision is ExecutionSafetyDecision.REVIEW
    assert len(executor.calls) == 0


def test_approved_action_reaches_executor():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    bridge.approve(action, approved_by="operator")
    result = bridge.execute(action, dry_run=False)

    assert result.executed is True
    assert len(executor.calls) == 1

    executed_action, dry_run = executor.calls[0]

    assert executed_action.status is ActionStatus.APPROVED
    assert dry_run is False


def test_idempotency_seen_blocks_execution():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    bridge.approve(action, approved_by="operator")

    result = bridge.execute(
        action,
        dry_run=False,
        idempotency_key="key-1",
        idempotency_seen=True,
    )

    assert result.executed is False
    assert result.safety.decision is ExecutionSafetyDecision.DENY
    assert len(executor.calls) == 0


def test_high_blast_radius_requires_review():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    result = bridge.execute(
        action,
        dry_run=False,
        blast_radius={"impact_score": 90},
    )

    assert result.executed is False
    assert result.safety.decision is ExecutionSafetyDecision.REVIEW
    assert len(executor.calls) == 0


def test_destructive_action_requires_approval():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)

    action = Action(
        action_id="act-delete",
        action_type="delete_instance",
    )

    result = bridge.execute(action, dry_run=False)

    assert result.executed is False
    assert result.safety.decision is ExecutionSafetyDecision.REVIEW
    assert result.requires_human_approval is True
    assert len(executor.calls) == 0


def test_execution_result_preserved():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    result = bridge.execute(action, dry_run=True)

    assert result.execution_result == {
        "action_id": "act-1",
        "executed": True,
        "dry_run": True,
    }


def test_approval_evidence_is_preserved():
    executor = FakeExecutor()
    bridge = ApprovalExecutionBridge(executor=executor)
    action = Action()

    bridge.approve(action, approved_by="operator")
    result = bridge.execute(action, dry_run=False)

    assert result.evidence["approval_status"] == "approved"
    assert result.evidence["approved_by"] == "operator"


def test_clear_removes_approval_records():
    bridge = ApprovalExecutionBridge(executor=FakeExecutor())
    action = Action()

    bridge.submit(action)
    assert bridge.get("act-1") is not None

    bridge.clear()

    assert bridge.get("act-1") is None
