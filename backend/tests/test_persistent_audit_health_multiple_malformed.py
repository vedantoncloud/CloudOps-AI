import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_health_counts_multiple_malformed_evidence_claims(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    for run_id in ("run-valid", "run-bad-1", "run-bad-2"):
        store.claim(run_id, "recovery_completed", {"action_id": run_id})

    with sqlite3.connect(store.path) as connection:
        connection.executemany(
            """
            UPDATE audit_idempotency
            SET evidence_json = ?
            WHERE run_id = ? AND event_type = ?
            """,
            [
                ("{bad-one", "run-bad-1", "recovery_completed"),
                ("{bad-two", "run-bad-2", "recovery_completed"),
            ],
        )

    health = PersistentAuditHealthChecker(store.path).inspect()

    assert health.total_claims == 3
    assert health.evidence["malformed_evidence_claims"] == 2
    assert health.evidence["read_only"] is True
