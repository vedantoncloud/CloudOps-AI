import sqlite3
import json

import pytest

from autonomy.gitops import GitOpsChange, GitOpsChangeStatus, GitOpsEngine
from autonomy.gitops_registry import GitOpsChangeSetRegistry


def make_change_set():
    return GitOpsEngine().create_change_set(
        source_action_id="action-persist",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-persist",
                field="instance_type",
                current_value="t3.small",
                desired_value="t3.medium",
                reason="Improve capacity",
            )
        ],
        metadata={"tenant_id": "tenant-a"},
    )


def test_gitops_state_survives_restart_through_full_dry_run_lifecycle(tmp_path):
    database = tmp_path / "state" / "gitops.db"
    original = GitOpsChangeSetRegistry(database_path=database)
    change = make_change_set()
    original.register(change)
    original.approve(change.change_id, "operator")
    original.apply(change.change_id, dry_run=True)

    restarted = GitOpsChangeSetRegistry(database_path=database)
    recovered = restarted.require(change.change_id)
    assert recovered.status is GitOpsChangeStatus.APPLIED
    assert recovered.approved_by == "operator"
    assert recovered.metadata == {"tenant_id": "tenant-a"}
    assert recovered.changes[0].desired_value == "t3.medium"

    assert restarted.verify(
        change.change_id,
        observed_values={"ec2/i-persist/instance_type": "t3.medium"},
    )
    assert GitOpsChangeSetRegistry(database_path=database).require(
        change.change_id
    ).status is GitOpsChangeStatus.VERIFIED


def test_gitops_rejection_and_order_survive_restart(tmp_path):
    database = tmp_path / "gitops.db"
    registry = GitOpsChangeSetRegistry(database_path=database)
    first = make_change_set()
    second = GitOpsEngine().create_change_set(
        source_action_id="action-second",
        changes=[GitOpsChange("s3", "bucket-a", "versioning", True)],
    )
    registry.register(first)
    registry.register(second)
    registry.reject(first.change_id, "reviewer", "Insufficient evidence")

    restored = GitOpsChangeSetRegistry(database_path=database)
    assert [item.change_id for item in restored.list_all()] == [
        first.change_id,
        second.change_id,
    ]
    assert restored.require(first.change_id).metadata["rejection_reason"] == "Insufficient evidence"


def test_corrupt_gitops_record_fails_startup_instead_of_dropping_change(tmp_path):
    database = tmp_path / "gitops.db"
    registry = GitOpsChangeSetRegistry(database_path=database)
    change = make_change_set()
    registry.register(change)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE gitops_change_sets SET payload = ? WHERE change_id = ?",
            ("{broken", change.change_id),
        )

    with pytest.raises(json.JSONDecodeError):
        GitOpsChangeSetRegistry(database_path=database)


def test_gitops_persistence_failure_is_reported(tmp_path, monkeypatch):
    registry = GitOpsChangeSetRegistry(database_path=tmp_path / "gitops.db")
    monkeypatch.setattr(registry, "_persist", lambda _change: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        registry.register(make_change_set())
    assert len(registry) == 0


def test_lifecycle_write_failure_restores_previous_live_state(tmp_path, monkeypatch):
    registry = GitOpsChangeSetRegistry(database_path=tmp_path / "gitops.db")
    change = make_change_set()
    registry.register(change)
    monkeypatch.setattr(registry, "_persist", lambda _change: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        registry.approve(change.change_id, "operator")

    assert change.status is GitOpsChangeStatus.PENDING_APPROVAL
    assert change.approved_by is None
    assert GitOpsChangeSetRegistry(database_path=registry.database_path).require(
        change.change_id
    ).status is GitOpsChangeStatus.PENDING_APPROVAL
