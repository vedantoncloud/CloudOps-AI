import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_health_counts_pending_and_emitted_claims(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    store.claim("run-pending-50", "recovery_completed", {"action_id": "pending"})
    store.claim("run-emitted-50", "recovery_completed", {"action_id": "emitted"})

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET status = 'emitted'
            WHERE run_id = ? AND event_type = ?
            """,
            ("run-emitted-50", "recovery_completed"),
        )

    health = PersistentAuditHealthChecker(store.path).inspect()

    assert health.total_claims == 2
    assert health.pending_claims == 1
    assert health.emitted_claims == 1
    assert health.evidence["consistent"] is True
