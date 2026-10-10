from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_active_pending_claim_cannot_be_reclaimed(tmp_path):
    store = PersistentAuditIdempotencyStore(
        tmp_path / "active-claim.db",
        lease_seconds=60,
    )
    evidence = {"source": "test", "attempt": 1}

    first = store.claim("run-active", "reconciliation", evidence)
    second = store.claim("run-active", "reconciliation", evidence)

    assert first.emitted is True
    assert first.claim_token
    assert second.emitted is False
    assert second.claim_token == ""
    assert second.evidence == evidence
