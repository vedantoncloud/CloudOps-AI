import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_expired_emitted_claim_is_never_reclaimed(tmp_path):
    database = tmp_path / "audit_idempotency.db"
    store = PersistentAuditIdempotencyStore(database, lease_seconds=1)

    original = store.claim(
        "run-emitted-terminal",
        "audit.completed",
        {"result": "success"},
    )

    assert original.emitted is True
    assert original.claim_token

    assert store.mark_emitted(
        original.run_id,
        original.event_type,
        original.claim_token,
    ) is True

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?
            WHERE run_id = ? AND event_type = ?
            """,
            (0, original.run_id, original.event_type),
        )

    reclaimed = store.claim(
        original.run_id,
        original.event_type,
        {"result": "success"},
    )

    assert reclaimed.emitted is False
    assert reclaimed.claim_token == ""

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT status, claim_token, claimed_at
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            (original.run_id, original.event_type),
        ).fetchone()

    assert row is not None
    assert row[0] == "emitted"
    assert row[1] == original.claim_token
    assert row[2] == 0

    repeated = store.claim(
        original.run_id,
        original.event_type,
        {"result": "success"},
    )

    assert repeated.emitted is False
    assert repeated.claim_token == ""
