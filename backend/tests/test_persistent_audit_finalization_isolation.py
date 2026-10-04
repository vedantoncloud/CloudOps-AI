import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_finalization_cannot_cross_audit_event_boundaries(tmp_path):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    first = store.claim(
        "isolation-run",
        "deployment.completed",
        {"service": "api"},
    )
    second = store.claim(
        "isolation-run",
        "deployment.failed",
        {"service": "worker"},
    )

    assert first.emitted is True
    assert second.emitted is True

    assert store.mark_emitted(
        "wrong-run",
        "deployment.completed",
        first.claim_token,
    ) is False

    assert store.mark_emitted(
        "isolation-run",
        "deployment.failed",
        first.claim_token,
    ) is False

    assert store.mark_emitted(
        "isolation-run",
        "deployment.completed",
        second.claim_token,
    ) is False

    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT event_type, status, claim_token "
            "FROM audit_idempotency ORDER BY event_type"
        ).fetchall()

    assert all(row[1] == "pending" for row in before)

    assert store.mark_emitted(
        "isolation-run",
        "deployment.completed",
        first.claim_token,
    ) is True

    assert store.mark_emitted(
        "isolation-run",
        "deployment.failed",
        second.claim_token,
    ) is True

    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT event_type, status, claim_token "
            "FROM audit_idempotency ORDER BY event_type"
        ).fetchall()

    assert len(after) == 2
    assert all(row[1] == "emitted" for row in after)
    assert after[0][2] == second.claim_token
    assert after[1][2] == first.claim_token
