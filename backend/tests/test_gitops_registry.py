from autonomy.gitops import (
    GitOpsChange,
    GitOpsChangeStatus,
    GitOpsEngine,
)
from autonomy.gitops_registry import GitOpsChangeSetRegistry


def make_change():
    return GitOpsChange(
        resource_type="ec2",
        resource_id="i-123",
        field="instance_type",
        desired_value="t3.large",
        current_value="t3.medium",
        reason="Resize instance",
    )


def make_change_set(*, requires_approval=True):
    return GitOpsEngine().create_change_set(
        source_action_id="action-1",
        changes=[make_change()],
        requires_approval=requires_approval,
    )


def test_register_and_get_change_set():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)

    assert registry.get(change_set.change_id) is change_set


def test_missing_change_set_returns_none():
    registry = GitOpsChangeSetRegistry()

    assert registry.get("missing-change") is None


def test_require_missing_change_set_raises():
    registry = GitOpsChangeSetRegistry()

    try:
        registry.require("missing-change")
    except KeyError as exc:
        assert "GitOps change set not found" in str(exc)
    else:
        raise AssertionError("Expected KeyError")


def test_duplicate_registration_is_rejected():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)

    try:
        registry.register(change_set)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_list_all_returns_registered_changes():
    registry = GitOpsChangeSetRegistry()

    first = make_change_set()
    second = GitOpsEngine().create_change_set(
        source_action_id="action-2",
        changes=[make_change()],
    )

    registry.register(first)
    registry.register(second)

    changes = registry.list_all()

    assert len(changes) == 2
    assert first in changes
    assert second in changes


def test_list_pending_returns_only_pending_approval_changes():
    registry = GitOpsChangeSetRegistry()

    pending = make_change_set()

    approved = GitOpsEngine().create_change_set(
        source_action_id="action-2",
        changes=[make_change()],
    )

    registry.register(pending)
    registry.register(approved)

    registry.approve(
        approved.change_id,
        "operator",
    )

    pending_changes = registry.list_pending()

    assert len(pending_changes) == 1
    assert pending_changes[0] is pending


def test_approve_updates_registered_change():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)

    result = registry.approve(
        change_set.change_id,
        "operator",
    )

    assert result is change_set
    assert change_set.status == GitOpsChangeStatus.APPROVED
    assert change_set.approved_by == "operator"


def test_reject_updates_registered_change():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)

    result = registry.reject(
        change_set.change_id,
        "operator",
        "Risk too high",
    )

    assert result is change_set
    assert change_set.status == GitOpsChangeStatus.REJECTED
    assert change_set.metadata["rejected_by"] == "operator"


def test_apply_uses_registered_change_set():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)
    registry.approve(
        change_set.change_id,
        "operator",
    )

    result = registry.apply(
        change_set.change_id,
        dry_run=True,
    )

    assert result.success is True
    assert result.dry_run is True
    assert result.status == GitOpsChangeStatus.APPLIED


def test_real_apply_remains_disabled():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)
    registry.approve(
        change_set.change_id,
        "operator",
    )

    result = registry.apply(
        change_set.change_id,
        dry_run=False,
    )

    assert result.success is False
    assert result.status == GitOpsChangeStatus.FAILED


def test_verify_uses_registered_change_set():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)
    registry.approve(
        change_set.change_id,
        "operator",
    )

    applied = registry.apply(
        change_set.change_id,
    )

    assert applied.success is True

    verified = registry.verify(
        change_set.change_id,
        observed_values={
            "ec2/i-123/instance_type": "t3.large",
        },
    )

    assert verified is True
    assert change_set.status == GitOpsChangeStatus.VERIFIED


def test_verify_failure_updates_registered_state():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)
    registry.approve(
        change_set.change_id,
        "operator",
    )

    registry.apply(change_set.change_id)

    verified = registry.verify(
        change_set.change_id,
        observed_values={
            "ec2/i-123/instance_type": "t3.medium",
        },
    )

    assert verified is False
    assert change_set.status == GitOpsChangeStatus.FAILED


def test_clear_removes_all_changes():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)

    assert len(registry) == 1

    registry.clear()

    assert len(registry) == 0
    assert registry.get(change_set.change_id) is None


def test_registry_length_tracks_changes():
    registry = GitOpsChangeSetRegistry()

    assert len(registry) == 0

    registry.register(make_change_set())

    assert len(registry) == 1


def test_registry_preserves_change_identity():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)

    retrieved = registry.require(change_set.change_id)

    assert retrieved is change_set
    assert retrieved.source_action_id == "action-1"


def test_approval_boundary_is_preserved():
    registry = GitOpsChangeSetRegistry()
    change_set = make_change_set()

    registry.register(change_set)

    result = registry.apply(
        change_set.change_id,
    )

    assert result.success is False
    assert change_set.status == GitOpsChangeStatus.PENDING_APPROVAL
