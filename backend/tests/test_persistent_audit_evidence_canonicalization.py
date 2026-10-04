import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_reordered_evidence_keys_do_not_create_duplicate_claim(tmp_path):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    first = store.claim(
        "run-canonical",
        "deployment.completed",
        {"service": "api", "details": {"region": "ap-south-1", "status": "ok"}},
    )
    second = store.claim(
        "run-canonical",
        "deployment.completed",
        {"details": {"status": "ok", "region": "ap-south-1"}, "service": "api"},
    )

    assert first.emitted is True
    assert second.emitted is False
    assert first.claim_token
    assert second.claim_token == ""

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM audit_idempotency"
        ).fetchone()[0]

    assert rows == 1