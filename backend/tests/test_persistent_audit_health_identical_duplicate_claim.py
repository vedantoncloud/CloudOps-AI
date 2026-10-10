from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_identical_duplicate_claim_is_idempotent(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "identical-claim.db")
    evidence = {"source": "test", "attempt": 1}

    first = store.claim("run-identical", "reconciliation", evidence)
    second = store.claim("run-identical", "reconciliation", evidence)

    assert first.emitted is True
    assert first.claim_token
    assert second.emitted is False
    assert second.claim_token == ""
    assert second.evidence == evidence
