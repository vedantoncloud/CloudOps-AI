import json
import sqlite3

import pytest

from autonomy.action_plan_store import ActionPlanStore
from autonomy.gitops_registry import GitOpsChangeSetRegistry
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from verify_database_backup import verify_backup


@pytest.mark.parametrize(
    ("store", "build"),
    [
        ("audit", "audit"),
        ("idempotency", "idempotency"),
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
    elif build == "idempotency":
        idempotency_store = PersistentAuditIdempotencyStore(backup)
        claim = idempotency_store.claim("run-1", "failure", {"result": "failed"})
        assert idempotency_store.mark_emitted("run-1", "failure", claim.claim_token)
        idempotency_store.close()
    elif build == "plans":
        ActionPlanStore(backup)
    else:
        GitOpsChangeSetRegistry(database_path=backup)

    original = backup.read_bytes()
    result = verify_backup(store, backup)

    assert result == {"store": store, "records_loaded": 1 if build in {"audit", "idempotency"} else 0}
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


def test_restore_drill_rejects_inconsistent_idempotency_backup(tmp_path):
    backup = tmp_path / "bad-idempotency.db"
    store = PersistentAuditIdempotencyStore(backup)
    store.close()
    with sqlite3.connect(backup) as connection:
        connection.execute(
            "INSERT INTO audit_idempotency "
            "(run_id, event_type, evidence_json, status, claim_token, claimed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("run-bad", "failure", '{"ok":true}', "unknown", "", 0),
        )

    with pytest.raises(ValueError, match="inconsistent claims"):
        verify_backup("idempotency", backup)


@pytest.mark.parametrize(
    ("store", "table", "columns"),
    [
        ("audit", "audit_events", ("event_json", "event_hash")),
        (
            "idempotency",
            "audit_idempotency",
            ("run_id", "event_type", "evidence_json", "status", "claimed_at"),
        ),
        ("action-plans", "action_plans", ("action_id", "payload", "created_order")),
        ("gitops", "gitops_change_sets", ("change_id", "payload")),
    ],
)
def test_restore_drill_rejects_incomplete_store_schema(tmp_path, store, table, columns):
    backup = tmp_path / f"incomplete-{store}.db"
    column_sql = ", ".join(f"{column} TEXT" for column in columns)
    with sqlite3.connect(backup) as connection:
        connection.execute(f"CREATE TABLE {table} ({column_sql})")

    with pytest.raises(ValueError, match="schema is incomplete"):
        verify_backup(store, backup)


def test_restore_drill_rejects_non_contiguous_audit_event_sequences(tmp_path):
    from autonomy.persistent_audit_trail import PersistentAuditTrail

    backup = tmp_path / "audit-sequence-gap.db"
    trail = PersistentAuditTrail(backup)
    trail.record(
        action_id="a1", action_type="inspect", resource_type="instance", resource_id="i-1",
        old_status="running", new_status="running", event="inspection_completed",
    )
    with sqlite3.connect(backup) as connection:
        connection.execute("UPDATE audit_events SET sequence = 2 WHERE sequence = 1")

    with pytest.raises(ValueError, match="sequence is not contiguous"):
        verify_backup("audit", backup)


@pytest.mark.parametrize(
    ("store", "invalid_kind", "expected_error"),
    [
        ("action-plans", "zero_order", "positive integer"),
        ("action-plans", "duplicate_order", "contains duplicates"),
        ("action-plans", "identity_drift", "does not match its primary key"),
        ("gitops", "negative_order", "positive integer"),
        ("gitops", "duplicate_order", "contains duplicates"),
        ("gitops", "identity_drift", "does not match its primary key"),
        ("gitops", "invalid_metadata", "metadata is invalid"),
    ],
)
def test_restore_drill_rejects_import_invalid_plan_and_gitops_records(
    tmp_path, store, invalid_kind, expected_error
):
    backup = tmp_path / f"invalid-{store}-{invalid_kind}.db"
    if store == "action-plans":
        ActionPlanStore(backup)
        table = "action_plans"
        key_column = "action_id"
        base_payload = {"action_id": "plan-1"}
        insert = (
            "INSERT INTO action_plans (action_id, tenant_id, payload, created_order) "
            "VALUES (?, ?, ?, ?)"
        )
        first = ("plan-1", "tenant-1", json.dumps(base_payload), 1)
        second = ("plan-2", "tenant-1", json.dumps({"action_id": "plan-2"}), 2)
    else:
        GitOpsChangeSetRegistry(database_path=backup)
        table = "gitops_change_sets"
        key_column = "change_id"
        base_payload = {"change_id": "change-1", "metadata": {}}
        insert = (
            "INSERT INTO gitops_change_sets (change_id, payload, created_order) "
            "VALUES (?, ?, ?)"
        )
        first = ("change-1", json.dumps(base_payload), 1)
        second = ("change-2", json.dumps({"change_id": "change-2", "metadata": {}}), 2)

    if invalid_kind == "identity_drift":
        if store == "action-plans":
            first = (first[0], first[1], json.dumps({"action_id": "different"}), first[3])
        else:
            first = (first[0], json.dumps({"change_id": "different", "metadata": {}}), first[2])
    elif invalid_kind == "invalid_metadata":
        first = (first[0], json.dumps({"change_id": "change-1", "metadata": []}), first[2])
    elif invalid_kind == "zero_order":
        first = (first[0], first[1], first[2], 0)
    elif invalid_kind == "negative_order":
        first = (first[0], first[1], -1)
    elif invalid_kind == "duplicate_order":
        if store == "action-plans":
            second = (second[0], second[1], second[2], 1)
        else:
            second = (second[0], second[1], 1)

    with sqlite3.connect(backup) as connection:
        connection.execute(insert, first)
        if invalid_kind == "duplicate_order":
            connection.execute(insert, second)

    original = backup.read_bytes()
    with pytest.raises(ValueError, match=expected_error):
        verify_backup(store, backup)
    assert backup.read_bytes() == original
