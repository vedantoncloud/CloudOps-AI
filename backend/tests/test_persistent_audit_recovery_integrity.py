import sqlite3
import time

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_expired_pending_claim_can_be_reclaimed(tmp_path):
    database = tmp_path / "recovery.db"
    store = PersistentAuditIdempotencyStore(database, lease_seconds=1)
    evidence = {"action_id": "recover-1", "outcome": "failed"}

    first = store.claim("recovery-run", "recovery_failed", evidence)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_idempotency SET claimed_at = ?",
            (time.time() - 10,),
        )

    second = store.claim("recovery-run", "recovery_failed", evidence)

    assert first.emitted is True
    assert second.emitted is True
    assert first.claim_token
    assert second.claim_token
    assert first.claim_token != second.claim_token


def test_stale_worker_cannot_finalize_reclaimed_claim(tmp_path):
    database = tmp_path / "stale.db"
    store = PersistentAuditIdempotencyStore(database, lease_seconds=1)
    evidence = {"action_id": "recover-2", "outcome": "failed"}

    first = store.claim("recovery-run", "recovery_failed", evidence)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_idempotency SET claimed_at = ?",
            (time.time() - 10,),
        )

    second = store.claim("recovery-run", "recovery_failed", evidence)

    assert store.mark_emitted(
        "recovery-run", "recovery_failed", first.claim_token
    ) is False

    assert store.mark_emitted(
        "recovery-run", "recovery_failed", second.claim_token
    ) is True

    assert store.claim(
        "recovery-run", "recovery_failed", evidence
    ).emitted is False
