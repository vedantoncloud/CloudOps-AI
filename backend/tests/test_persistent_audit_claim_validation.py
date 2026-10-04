import sqlite3

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


@pytest.mark.parametrize(
    ("run_id", "event_type", "message"),
    [
        ("", "deployment.completed", "run_id is required"),
        ("run-1", "", "event_type is required"),
        ("   ", "deployment.completed", "run_id is required"),
        ("run-1", "   ", "event_type is required"),
        ("   ", "   ", "run_id is required"),
    ],
)
def test_invalid_claim_identifiers_do_not_modify_database(
    tmp_path, run_id, event_type, message
):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    with pytest.raises(ValueError, match=message):
        store.claim(run_id, event_type, {"status": "ok"})

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT run_id, event_type, evidence_json, status "
            "FROM audit_idempotency"
        ).fetchall()

    assert rows == []