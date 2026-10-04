import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_audit_lookup_is_consistent_and_read_only(tmp_path):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    store.claim(
        "lookup-run",
        "deployment.completed",
        {"service": "api", "result": "success"},
    )

    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT run_id, event_type, evidence_json, status, "
            "claim_token, claimed_at FROM audit_idempotency"
        ).fetchall()

    assert store.contains("lookup-run", "deployment.completed") is True
    assert store.contains(" lookup-run ", " deployment.completed ") is True
    assert store.contains("missing-run", "deployment.completed") is False
    assert store.contains("lookup-run", "deployment.failed") is False
    assert store.contains("", "deployment.completed") is False
    assert store.contains("lookup-run", "") is False
    assert store.contains("   ", "deployment.completed") is False

    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT run_id, event_type, evidence_json, status, "
            "claim_token, claimed_at FROM audit_idempotency"
        ).fetchall()

    assert before == after
    assert len(after) == 1
