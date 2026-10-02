from __future__ import annotations

import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_pending_evidence_preserves_valid_json_as_dictionary(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim(
        "run-1",
        "recovery_failed",
        {"action_id": "a-1", "source": "test"},
    )

    pending = PersistentAuditHealthChecker(path).list_pending()

    assert pending[0]["evidence"] == {
        "action_id": "a-1",
        "source": "test",
    }


def test_pending_evidence_malformed_json_uses_raw_fallback(tmp_path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO audit_idempotency(
                run_id,
                event_type,
                evidence_json,
                status,
                claim_token,
                claimed_at
            )
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            ("run-1", "recovery_failed", "{invalid-json", "token-1", 1.0),
        )

    pending = PersistentAuditHealthChecker(path).list_pending()

    assert len(pending) == 1
    assert pending[0]["evidence"] == {"raw": "{invalid-json"}


def test_pending_order_uses_run_id_then_event_type(tmp_path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    with sqlite3.connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO audit_idempotency(
                run_id,
                event_type,
                evidence_json,
                status,
                claim_token,
                claimed_at
            )
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            [
                ("run-1", "z_event", '{"key":"z"}', "t1", 1.0),
                ("run-1", "a_event", '{"key":"a"}', "t2", 2.0),
                ("run-0", "m_event", '{"key":"m"}', "t3", 3.0),
            ],
        )

    pending = PersistentAuditHealthChecker(path).list_pending()

    assert [
        (item["run_id"], item["event_type"])
        for item in pending
    ] == [
        ("run-0", "m_event"),
        ("run-1", "a_event"),
        ("run-1", "z_event"),
    ]


def test_malformed_evidence_does_not_break_health_inspection(tmp_path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO audit_idempotency(
                run_id,
                event_type,
                evidence_json,
                status,
                claim_token,
                claimed_at
            )
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            ("run-1", "recovery_failed", "not-json", "token-1", 1.0),
        )

    health = PersistentAuditHealthChecker(path).inspect()

    assert health.total_claims == 1
    assert health.pending_claims == 1
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is True
