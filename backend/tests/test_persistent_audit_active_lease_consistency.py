import sqlite3
import time

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_active_lease_preserves_original_claim_state(tmp_path):
    database = tmp_path / "active-lease.db"
    store = PersistentAuditIdempotencyStore(database, lease_seconds=60)
    evidence = {"action_id": "active-1", "outcome": "failed"}

    first = store.claim("active-run", "recovery_failed", evidence)

    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchone()

    second = store.claim("active-run", "recovery_failed", evidence)

    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchone()

    assert first.emitted is True
    assert second.emitted is False
    assert second.claim_token == ""
    assert before[0] == "pending"
    assert after == before


def test_reclaimed_claim_refreshes_lease_timestamp(tmp_path):
    database = tmp_path / "lease-refresh.db"
    store = PersistentAuditIdempotencyStore(database, lease_seconds=1)
    evidence = {"action_id": "refresh-1", "outcome": "failed"}

    first = store.claim("refresh-run", "recovery_failed", evidence)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_idempotency SET claimed_at = ?",
            (time.time() - 10,),
        )

    second = store.claim("refresh-run", "recovery_failed", evidence)

    with sqlite3.connect(database) as connection:
        status, token, claimed_at = connection.execute(
            "SELECT status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchone()

    assert second.emitted is True
    assert second.claim_token != first.claim_token
    assert status == "pending"
    assert token == second.claim_token
    assert claimed_at > time.time() - 5
