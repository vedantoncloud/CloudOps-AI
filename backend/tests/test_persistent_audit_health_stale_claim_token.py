import time

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_stale_claim_token_cannot_emit_reclaimed_claim(tmp_path):
    store = PersistentAuditIdempotencyStore(
        tmp_path / "stale-token.db",
        lease_seconds=1,
    )
    run_id = "run-stale-token"
    event_type = "reconciliation"
    evidence = {"source": "test", "attempt": 1}

    first = store.claim(run_id, event_type, evidence)
    assert first.emitted is True
    assert first.claim_token

    time.sleep(1.1)

    second = store.claim(run_id, event_type, evidence)
    assert second.emitted is True
    assert second.claim_token
    assert second.claim_token != first.claim_token

    result = store.mark_emitted(run_id, event_type, first.claim_token)
    assert result is False

    third = store.claim(run_id, event_type, evidence)
    assert third.emitted is False
    assert third.claim_token == ""
