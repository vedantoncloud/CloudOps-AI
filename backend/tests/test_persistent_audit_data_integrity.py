from __future__ import annotations

import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_health_inspection_does_not_mutate_audit_records(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    claim = store.claim(
        "readonly-run",
        "recovery_failed",
        {"action_id": "readonly"},
    )

    with sqlite3.connect(path) as connection:
        before = connection.execute(
            """
            SELECT run_id, event_type, evidence_json, status,
                   claim_token, claimed_at
            FROM audit_idempotency
            """
        ).fetchall()

    checker = PersistentAuditHealthChecker(path)
    checker.inspect()
    checker.list_pending()
    checker.inspect()

    with sqlite3.connect(path) as connection:
        after = connection.execute(
            """
            SELECT run_id, event_type, evidence_json, status,
                   claim_token, claimed_at
            FROM audit_idempotency
            """
        ).fetchall()

    assert after == before
    assert claim.claim_token


def test_pending_listing_handles_malformed_stored_evidence(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim(
        "malformed-run",
        "recovery_failed",
        {"action_id": "malformed"},
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET evidence_json = ?
            WHERE run_id = ? AND event_type = ?
            """,
            (
                "{not-valid-json",
                "malformed-run",
                "recovery_failed",
            ),
        )

    pending = PersistentAuditHealthChecker(path).list_pending()

    assert len(pending) == 1
    assert pending[0]["run_id"] == "malformed-run"
    assert pending[0]["event_type"] == "recovery_failed"
    assert pending[0]["evidence"] == {"raw": "{not-valid-json"}


def test_health_marks_unknown_status_as_inconsistent(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim(
        "unknown-status-run",
        "recovery_failed",
        {"action_id": "unknown-status"},
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET status = 'unexpected'
            WHERE run_id = ?
            """,
            ("unknown-status-run",),
        )

    health = PersistentAuditHealthChecker(path).inspect()

    assert health.total_claims == 1
    assert health.pending_claims == 0
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is False