from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_invalid_claim_token_cannot_mark_claim_emitted(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "invalid-token.db")
    run_id = "run-invalid-token"
    event_type = "reconciliation"
    evidence = {"source": "test", "attempt": 1}

    claim = store.claim(run_id, event_type, evidence)
    assert claim.emitted is True
    assert claim.claim_token

    result = store.mark_emitted(run_id, event_type, "wrong-token")

    assert result is False

    duplicate = store.claim(run_id, event_type, evidence)
    assert duplicate.emitted is False
    assert duplicate.claim_token == ""
