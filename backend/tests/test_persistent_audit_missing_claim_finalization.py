import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_finalization_of_missing_claim_does_not_create_record(tmp_path):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    result = store.mark_emitted(
        "missing-run",
        "deployment.completed",
        "unknown-claim-token",
    )

    assert result is False

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT run_id, event_type, status, claim_token
            FROM audit_idempotency
            """
        ).fetchall()

    assert rows == []
    assert store.contains("missing-run", "deployment.completed") is False
