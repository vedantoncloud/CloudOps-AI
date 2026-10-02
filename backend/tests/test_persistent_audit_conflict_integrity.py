from __future__ import annotations

import sqlite3

import pytest

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def _read_record(path, run_id, event_type):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            """
            SELECT evidence_json, status, claim_token, claimed_at
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            (run_id, event_type),
        ).fetchone()


def test_conflicting_pending_evidence_preserves_original_claim(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    original = store.claim(
        "conflict-pending",
        "recovery_failed",
        {"action_id": "original", "source": "test"},
    )

    before = _read_record(path, "conflict-pending", "recovery_failed")

    with pytest.raises(ValueError, match="Conflicting audit evidence"):
        store.claim(
            "conflict-pending",
            "recovery_failed",
            {"action_id": "different", "source": "test"},
        )

    after = _read_record(path, "conflict-pending", "recovery_failed")

    assert after == before
    assert original.emitted is True
    assert original.claim_token == before[2]

    health = PersistentAuditHealthChecker(path).inspect()
    assert health.total_claims == 1
    assert health.pending_claims == 1
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is True


def test_conflicting_emitted_evidence_preserves_finalized_record(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    original = store.claim(
        "conflict-emitted",
        "recovery_completed",
        {"action_id": "finalized"},
    )

    assert store.mark_emitted(
        "conflict-emitted",
        "recovery_completed",
        original.claim_token,
    ) is True

    before = _read_record(path, "conflict-emitted", "recovery_completed")

    with pytest.raises(ValueError, match="Conflicting audit evidence"):
        store.claim(
            "conflict-emitted",
            "recovery_completed",
            {"action_id": "tampered"},
        )

    after = _read_record(path, "conflict-emitted", "recovery_completed")

    assert after == before
    assert after[1] == "emitted"

    health = PersistentAuditHealthChecker(path).inspect()
    assert health.total_claims == 1
    assert health.pending_claims == 0
    assert health.emitted_claims == 1
    assert health.evidence["consistent"] is True