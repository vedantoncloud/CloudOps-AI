from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_wrong_event_type_cannot_mark_claim_emitted(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "wrong-event-type.db")
    run_id = "run-correct"
    event_type = "reconciliation"
    evidence = {"source": "test", "attempt": 1}

    claim = store.claim(run_id, event_type, evidence)
    assert claim.emitted is True
    assert claim.claim_token

    result = store.mark_emitted(
        run_id,
        "incorrect-event",
        claim.claim_token,
    )
    assert result is False

    duplicate = store.claim(run_id, event_type, evidence)
    assert duplicate.emitted is False
    assert duplicate.claim_token == ""
