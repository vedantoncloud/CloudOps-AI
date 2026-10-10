import sqlite3

import pytest

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_audit_store_rejects_null_evidence(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    store.claim("run-null-46", "recovery_completed", {"action_id": "action-46"})

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="NOT NULL constraint failed",
        ):
            connection.execute(
                """
                UPDATE audit_idempotency
                SET evidence_json = NULL
                WHERE run_id = ? AND event_type = ?
                """,
                ("run-null-46", "recovery_completed"),
            )
