from __future__ import annotations

import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_active_lease_is_not_reclaimed_early(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path, lease_seconds=60)

    first = store.claim("lease-run", "recovery_failed", {"action": "x"})
    second = store.claim("lease-run", "recovery_failed", {"action": "x"})

    assert first.emitted is True
    assert second.emitted is False
    assert second.claim_token == ""


def test_expired_lease_can_be_reclaimed_with_new_token(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path, lease_seconds=1)

    first = store.claim("lease-run", "recovery_failed", {"action": "x"})

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = 0
            WHERE run_id = ? AND event_type = ?
            """,
            ("lease-run", "recovery_failed"),
        )

    second = store.claim("lease-run", "recovery_failed", {"action": "x"})

    assert second.emitted is True
    assert second.claim_token
    assert second.claim_token != first.claim_token


def test_old_claim_cannot_finalize_reclaimed_lease(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path, lease_seconds=1)

    first = store.claim("lease-run", "recovery_failed", {"action": "x"})

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = 0
            WHERE run_id = ? AND event_type = ?
            """,
            ("lease-run", "recovery_failed"),
        )

    second = store.claim("lease-run", "recovery_failed", {"action": "x"})

    assert store.mark_emitted(
        "lease-run", "recovery_failed", first.claim_token
    ) is False

    assert store.mark_emitted(
        "lease-run", "recovery_failed", second.claim_token
    ) is True

    retry = store.claim("lease-run", "recovery_failed", {"action": "x"})
    assert retry.emitted is False
    assert retry.claim_token == ""
