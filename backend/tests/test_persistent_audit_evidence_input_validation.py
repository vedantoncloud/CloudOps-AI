import sqlite3

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


@pytest.mark.parametrize("evidence", [None, [], "invalid", 42])
def test_invalid_evidence_is_rejected_without_creating_claim(
    tmp_path, evidence
):
    database = tmp_path / "invalid-evidence.db"
    store = PersistentAuditIdempotencyStore(database)

    with pytest.raises(
        ValueError, match="evidence must be a dictionary"
    ):
        store.claim("invalid-run", "recovery_failed", evidence)

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM audit_idempotency"
        ).fetchone()[0]

    assert count == 0
