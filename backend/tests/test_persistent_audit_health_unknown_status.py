import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_health_detects_unknown_claim_status(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    store.claim("run-unknown-51", "recovery_completed", {"action_id": "action-51"})

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET status = 'unknown_status'
            WHERE run_id = ? AND event_type = ?
            """,
            ("run-unknown-51", "recovery_completed"),
        )

    health = PersistentAuditHealthChecker(store.path).inspect()

    assert health.total_claims == 1
    assert health.pending_claims == 0
    assert health.emitted_claims == 0
    assert health.evidence["unknown_status_claims"] == 1
    assert health.evidence["consistent"] is False
