import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_health_inspection_does_not_modify_store(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    store.claim("run-readonly-47", "recovery_completed", {"action_id": "action-47"})

    with sqlite3.connect(store.path) as connection:
        before = connection.execute(
            """
            SELECT run_id, event_type, status, evidence_json, claimed_at
            FROM audit_idempotency
            ORDER BY run_id, event_type
            """
        ).fetchall()

    checker = PersistentAuditHealthChecker(store.path)
    checker.inspect()
    checker.list_pending()

    with sqlite3.connect(store.path) as connection:
        after = connection.execute(
            """
            SELECT run_id, event_type, status, evidence_json, claimed_at
            FROM audit_idempotency
            ORDER BY run_id, event_type
            """
        ).fetchall()

    assert after == before
