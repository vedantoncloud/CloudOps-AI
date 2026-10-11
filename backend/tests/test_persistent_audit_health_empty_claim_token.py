import pytest

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_empty_claim_token_cannot_mark_claim_emitted(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "empty-token.db")
    run_id = "run-empty-token"
    event_type = "reconciliation"
    evidence = {"source": "test", "attempt": 1}

    claim = store.claim(run_id, event_type, evidence)
    assert claim.emitted is True
    assert claim.claim_token

    with pytest.raises(ValueError, match="claim_token is required"):
        store.mark_emitted(run_id, event_type, " ")

    duplicate = store.claim(run_id, event_type, evidence)
    assert duplicate.emitted is False
    assert duplicate.claim_token == ""
