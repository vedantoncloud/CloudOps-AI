import sqlite3
import time

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_lease_remains_active_until_exact_expiry_boundary(
    tmp_path, monkeypatch
):
    database = tmp_path / "lease-boundary.db"
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    store = PersistentAuditIdempotencyStore(database, lease_seconds=10)
    evidence = {"action_id": "boundary-1", "outcome": "failed"}

    first = store.claim("boundary-run", "recovery_failed", evidence)

    clock[0] = 1009.999
    before_expiry = store.claim(
        "boundary-run", "recovery_failed", evidence
    )

    assert first.emitted is True
    assert before_expiry.emitted is False
    assert before_expiry.claim_token == ""

    with sqlite3.connect(database) as connection:
        status, token, claimed_at = connection.execute(
            "SELECT status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchone()

    assert status == "pending"
    assert token == first.claim_token
    assert claimed_at == 1000.0

    clock[0] = 1010.0
    at_expiry = store.claim(
        "boundary-run", "recovery_failed", evidence
    )

    with sqlite3.connect(database) as connection:
        status, token, claimed_at = connection.execute(
            "SELECT status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchone()

    assert at_expiry.emitted is True
    assert at_expiry.claim_token != first.claim_token
    assert status == "pending"
    assert token == at_expiry.claim_token
    assert claimed_at == 1010.0
