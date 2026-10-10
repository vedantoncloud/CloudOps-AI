import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_health_inspection_counts_malformed_evidence(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    store.claim("run-health-44", "recovery_completed", {"action_id": "action-44"})

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET evidence_json = ?
            WHERE run_id = ? AND event_type = ?
            """,
            ("{invalid-json", "run-health-44", "recovery_completed"),
        )

    health = PersistentAuditHealthChecker(store.path).inspect()

    assert health.evidence["malformed_evidence_claims"] == 1
    assert health.evidence["read_only"] is True
