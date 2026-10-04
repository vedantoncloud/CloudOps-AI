import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_stale_claim_token_cannot_finalize_reclaimed_event(tmp_path):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database, lease_seconds=1)
    evidence = {"service": "api", "result": "success"}

    original = store.claim(
        "stale-token-run",
        "deployment.completed",
        evidence,
    )
    assert original.emitted is True

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_idempotency SET claimed_at = 0 "
            "WHERE run_id = ? AND event_type = ?",
            ("stale-token-run", "deployment.completed"),
        )

    reclaimed = store.claim(
        "stale-token-run",
        "deployment.completed",
        evidence,
    )

    assert reclaimed.emitted is True
    assert reclaimed.claim_token
    assert reclaimed.claim_token != original.claim_token

    stale_result = store.mark_emitted(
        "stale-token-run",
        "deployment.completed",
        original.claim_token,
    )
    assert stale_result is False

    current_result = store.mark_emitted(
        "stale-token-run",
        "deployment.completed",
        reclaimed.claim_token,
    )
    assert current_result is True

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT evidence_json, status, claim_token "
            "FROM audit_idempotency "
            "WHERE run_id = ? AND event_type = ?",
            ("stale-token-run", "deployment.completed"),
        ).fetchone()

    assert row == (
        '{"result":"success","service":"api"}',
        "emitted",
        reclaimed.claim_token,
    )
