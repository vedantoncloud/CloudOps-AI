from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.governance import GovernanceDecision, GovernanceManager


def create_action() -> ActionPlan:
    return ActionPlan(
        action_type="review_cpu_utilization",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-test123",
        ),
        reason="CPU utilization requires investigation.",
        risk=RiskLevel.MEDIUM,
        requires_approval=True,
    )


def test_submit_creates_pending_record():
    manager = GovernanceManager()
    action = create_action()

    record = manager.submit(action)

    assert record.action_id == action.action_id
    assert record.decision == GovernanceDecision.PENDING
    assert record.decided_by is None
    assert manager.get_record(action.action_id) == record


def test_submit_is_idempotent():
    manager = GovernanceManager()
    action = create_action()

    first = manager.submit(action)
    second = manager.submit(action)

    assert first == second


def test_approve_changes_action_status():
    manager = GovernanceManager()
    action = create_action()

    manager.submit(action)
    record = manager.approve(
        action,
        decided_by="admin",
        reason="Approved after review.",
    )

    assert record.decision == GovernanceDecision.APPROVED
    assert record.decided_by == "admin"
    assert record.reason == "Approved after review."
    assert action.status == ActionStatus.APPROVED


def test_reject_cancels_action():
    manager = GovernanceManager()
    action = create_action()

    manager.submit(action)
    record = manager.reject(
        action,
        decided_by="admin",
        reason="Blast radius is too high.",
    )

    assert record.decision == GovernanceDecision.REJECTED
    assert record.decided_by == "admin"
    assert action.status == ActionStatus.CANCELLED


def test_cancel_changes_action_status():
    manager = GovernanceManager()
    action = create_action()

    manager.submit(action)
    record = manager.cancel(
        action,
        decided_by="operator",
        reason="Cancelled by operator.",
    )

    assert record.decision == GovernanceDecision.CANCELLED
    assert action.status == ActionStatus.CANCELLED


def test_approve_requires_decision_maker():
    manager = GovernanceManager()
    action = create_action()
    manager.submit(action)

    try:
        manager.approve(action, decided_by="")
    except ValueError as exc:
        assert str(exc) == "decided_by cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_reject_requires_reason():
    manager = GovernanceManager()
    action = create_action()
    manager.submit(action)

    try:
        manager.reject(
            action,
            decided_by="admin",
            reason="",
        )
    except ValueError as exc:
        assert str(exc) == "reason cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_cannot_decide_twice():
    manager = GovernanceManager()
    action = create_action()
    manager.submit(action)

    manager.approve(action, decided_by="admin")

    try:
        manager.reject(
            action,
            decided_by="admin",
            reason="Too risky.",
        )
    except ValueError as exc:
        assert "already decided" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_missing_submission_is_rejected():
    manager = GovernanceManager()
    action = create_action()

    try:
        manager.approve(action, decided_by="admin")
    except ValueError as exc:
        assert str(exc) == "Action is not submitted for governance."
    else:
        raise AssertionError("Expected ValueError")


def test_list_pending_returns_only_pending_actions():
    manager = GovernanceManager()

    first = create_action()
    second = create_action()

    manager.submit(first)
    manager.submit(second)

    manager.approve(first, decided_by="admin")

    pending = manager.list_pending()

    assert len(pending) == 1
    assert pending[0].action_id == second.action_id
    assert pending[0].decision == GovernanceDecision.PENDING
