import time

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_expired_pending_claim_can_be_reclaimed(tmp_path):
    store = PersistentAuditIdempotencyStore(
        tmp_path / "expired-claim.db",
        lease_seconds=1,
    )
    evidence = {"source": "test", "attempt": 1}

    first = store.claim("run-expired", "reconciliation", evidence)
    assert first.emitted is True
    assert first.claim_token

    time.sleep(1.1)

    second = store.claim("run-expired", "reconciliation", evidence)

    assert second.emitted is True
    assert second.claim_token
    assert second.claim_token != first.claim_token
