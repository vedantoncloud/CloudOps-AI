import sqlite3

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


@pytest.mark.parametrize("finalize_first", [False, True])
def test_conflicting_evidence_preserves_existing_audit_record(
    tmp_path, finalize_first
):
    database = tmp_path / f"evidence-conflict-{finalize_first}.db"
    store = PersistentAuditIdempotencyStore(database)
    original = {"action_id": "conflict-1", "outcome": "failed"}

    claim = store.claim("conflict-run", "recovery_failed", original)

    if finalize_first:
        assert store.mark_emitted(
            "conflict-run", "recovery_failed", claim.claim_token
        )

    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT evidence_json, status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchone()

    with pytest.raises(ValueError, match="Conflicting audit evidence"):
        store.claim(
            "conflict-run",
            "recovery_failed",
            {"action_id": "conflict-1", "outcome": "success"},
        )

    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT evidence_json, status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchone()

    assert after == before
