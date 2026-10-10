from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_emitted_audit_claim_cannot_be_emitted_again(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "emitted-claim.db")
    evidence = {"source": "test", "attempt": 1}
    run_id = "run-emitted"
    event_type = "reconciliation"

    first = store.claim(run_id, event_type, evidence)
    assert first.emitted is True
    assert first.claim_token

    store.mark_emitted(run_id, event_type, first.claim_token)

    second = store.claim(run_id, event_type, evidence)

    assert second.emitted is False
    assert second.claim_token == ""
    assert second.evidence == evidence
