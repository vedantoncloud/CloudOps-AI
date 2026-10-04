import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_repeated_finalization_is_idempotent_and_preserves_record(tmp_path):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    claim = store.claim(
        "finalization-run",
        "deployment.completed",
        {"service": "api", "result": "success"},
    )

    assert claim.emitted is True
    assert claim.claim_token

    first = store.mark_emitted(
        "finalization-run",
        "deployment.completed",
        claim.claim_token,
    )

    with sqlite3.connect(database) as connection:
        finalized_record = connection.execute(
            "SELECT evidence_json, status, claim_token, claimed_at "
            "FROM audit_idempotency "
            "WHERE run_id = ? AND event_type = ?",
            ("finalization-run", "deployment.completed"),
        ).fetchone()

    second = store.mark_emitted(
        "finalization-run",
        "deployment.completed",
        claim.claim_token,
    )

    with sqlite3.connect(database) as connection:
        repeated_record = connection.execute(
            "SELECT evidence_json, status, claim_token, claimed_at "
            "FROM audit_idempotency "
            "WHERE run_id = ? AND event_type = ?",
            ("finalization-run", "deployment.completed"),
        ).fetchone()

    duplicate = store.claim(
        "finalization-run",
        "deployment.completed",
        {"service": "api", "result": "success"},
    )

    assert first is True
    assert second is False
    assert finalized_record == repeated_record
    assert finalized_record[1] == "emitted"
    assert duplicate.emitted is False
    assert duplicate.claim_token == ""