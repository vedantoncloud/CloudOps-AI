import sqlite3

import pytest

from autonomy.action_plan_store import ActionPlanStore
from autonomy.gitops_registry import GitOpsChangeSetRegistry
from verify_database_backup import verify_backup


@pytest.mark.parametrize(
    ("store", "build"),
    [
        ("audit", "audit"),
        ("action-plans", "plans"),
        ("gitops", "gitops"),
    ],
)
def test_restore_drill_loads_each_store_without_modifying_backup(tmp_path, store, build):
    backup = tmp_path / f"{store}.db"
    if build == "audit":
        from autonomy.persistent_audit_trail import PersistentAuditTrail

        trail = PersistentAuditTrail(backup)
        trail.record(
            action_id="a1", action_type="inspect", resource_type="instance", resource_id="i-1",
            old_status="running", new_status="running", event="inspection_completed",
        )
    elif build == "plans":
        ActionPlanStore(backup)
    else:
        GitOpsChangeSetRegistry(database_path=backup)

    original = backup.read_bytes()
    result = verify_backup(store, backup)

    assert result == {"store": store, "records_loaded": 1 if build == "audit" else 0}
    assert backup.read_bytes() == original


def test_restore_drill_rejects_sqlite_file_missing_expected_store(tmp_path):
    backup = tmp_path / "wrong.db"
    with sqlite3.connect(backup) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")

    with pytest.raises(ValueError, match="expected action-plans store"):
        verify_backup("action-plans", backup)


def test_restore_drill_rejects_corrupt_audit_chain(tmp_path):
    from autonomy.persistent_audit_trail import PersistentAuditTrail

    backup = tmp_path / "audit.db"
    trail = PersistentAuditTrail(backup)
    trail.record(
        action_id="a1", action_type="inspect", resource_type="instance", resource_id="i-1",
        old_status="running", new_status="running", event="inspection_completed",
    )
    with sqlite3.connect(backup) as connection:
        connection.execute("UPDATE audit_events SET event_hash = ?", ("0" * 64,))

    with pytest.raises(ValueError, match="hash chain failed"):
        verify_backup("audit", backup)
