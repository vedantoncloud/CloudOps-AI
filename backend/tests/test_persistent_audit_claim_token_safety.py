from __future__ import annotations

import sqlite3

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_valid_claim_token_transitions_pending_to_emitted(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    claim = store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    assert claim.emitted is True
    assert claim.claim_token

    assert store.mark_emitted(
        "run-1",
        "recovery_failed",
        claim.claim_token,
    ) is True

    retry = store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    assert retry.emitted is False
    assert retry.claim_token == ""


def test_wrong_token_cannot_mark_claim_emitted(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    claim = store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    assert store.mark_emitted(
        "run-1",
        "recovery_failed",
        "wrong-token",
    ) is False

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT status, claim_token
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            ("run-1", "recovery_failed"),
        ).fetchone()

    assert row == ("pending", claim.claim_token)


def test_stale_token_cannot_mark_reclaimed_claim_emitted(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path, lease_seconds=1)

    first = store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = 0
            WHERE run_id = ? AND event_type = ?
            """,
            ("run-1", "recovery_failed"),
        )

    second = store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    assert second.emitted is True
    assert second.claim_token
    assert second.claim_token != first.claim_token

    assert store.mark_emitted(
        "run-1",
        "recovery_failed",
        first.claim_token,
    ) is False

    assert store.mark_emitted(
        "run-1",
        "recovery_failed",
        second.claim_token,
    ) is True


@pytest.mark.parametrize(
    ("run_id", "event_type", "token", "message"),
    [
        ("", "recovery_failed", "token", "run_id is required"),
        ("run-1", "", "token", "event_type is required"),
        ("run-1", "recovery_failed", "", "claim_token is required"),
    ],
)
def test_mark_emitted_rejects_missing_identifiers(
    tmp_path,
    run_id,
    event_type,
    token,
    message,
):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    with pytest.raises(ValueError, match=message):
        store.mark_emitted(run_id, event_type, token)
