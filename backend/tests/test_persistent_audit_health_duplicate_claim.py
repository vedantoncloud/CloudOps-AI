import pytest

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_duplicate_claim_rejects_conflicting_evidence(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "duplicate-claim.db")

    store.claim("run-duplicate", "reconciliation", {"source": "first", "attempt": 1})

    with pytest.raises(ValueError, match="Conflicting audit evidence"):
        store.claim(
            "run-duplicate",
            "reconciliation",
            {"source": "second", "attempt": 2},
        )
