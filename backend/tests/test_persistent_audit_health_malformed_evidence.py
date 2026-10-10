import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_pending_listing_preserves_malformed_evidence_as_raw(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    store.claim("run-malformed", "recovery_completed", {"action_id": "action-43"})

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET evidence_json = ?
            WHERE run_id = ? AND event_type = ?
            """,
            ("{broken-json", "run-malformed", "recovery_completed"),
        )

    pending = PersistentAuditHealthChecker(store.path).list_pending()

    assert len(pending) == 1
    assert pending[0]["evidence"] == {"raw": "{broken-json"}
