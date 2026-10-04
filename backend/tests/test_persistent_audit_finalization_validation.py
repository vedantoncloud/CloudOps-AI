import sqlite3

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


@pytest.mark.parametrize(
    ("run_id", "event_type", "token", "message"),
    [
        ("", "deployment.completed", "valid-token", "run_id is required"),
        ("run-1", "", "valid-token", "event_type is required"),
        ("run-1", "deployment.completed", "", "claim_token is required"),
        ("   ", "deployment.completed", "valid-token", "run_id is required"),
        ("run-1", "   ", "valid-token", "event_type is required"),
        ("run-1", "deployment.completed", "   ", "claim_token is required"),
    ],
)
def test_invalid_finalization_inputs_do_not_modify_record(
    tmp_path, run_id, event_type, token, message
):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    claim = store.claim(
        "valid-run",
        "deployment.completed",
        {"service": "api", "result": "success"},
    )

    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT evidence_json, status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchall()

    with pytest.raises(ValueError, match=message):
        store.mark_emitted(run_id, event_type, token)

    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT evidence_json, status, claim_token, claimed_at "
            "FROM audit_idempotency"
        ).fetchall()

    assert before == after
    assert before[0][1] == "pending"
    assert before[0][2] == claim.claim_token
