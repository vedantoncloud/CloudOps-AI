from __future__ import annotations

import sqlite3

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_failed_claim_insert_leaves_no_partial_record(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_audit_insert
            BEFORE INSERT ON audit_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'injected insert failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected insert failure"):
        store.claim("rollback-run", "recovery_failed", {"action": "x"})

    with sqlite3.connect(path) as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            ("rollback-run", "recovery_failed"),
        ).fetchone()[0]

    assert count == 0


def test_claim_can_retry_after_insert_failure_is_removed(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_audit_insert
            BEFORE INSERT ON audit_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'injected insert failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        store.claim("retry-run", "recovery_failed", {"action": "x"})

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER reject_audit_insert")

    retry = store.claim("retry-run", "recovery_failed", {"action": "x"})

    assert retry.emitted is True
    assert retry.claim_token
    assert store.contains("retry-run", "recovery_failed") is True


def test_failed_mark_emitted_does_not_change_pending_claim(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    claim = store.claim("mark-run", "recovery_failed", {"action": "x"})

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_status_update
            BEFORE UPDATE OF status ON audit_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'injected update failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected update failure"):
        store.mark_emitted(
            "mark-run",
            "recovery_failed",
            claim.claim_token,
        )

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT status, claim_token
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            ("mark-run", "recovery_failed"),
        ).fetchone()

    assert row == ("pending", claim.claim_token)
