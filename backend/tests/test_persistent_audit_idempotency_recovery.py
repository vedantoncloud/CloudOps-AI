from __future__ import annotations

from pathlib import Path

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_claim_is_pending_until_marked_emitted(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    first = store.claim("run-123", "recovery_failed", {"action_id": "a-1"})
    second = store.claim("run-123", "recovery_failed", {"action_id": "a-1"})

    assert first.emitted is True
    assert first.claim_token
    assert second.emitted is False

    assert store.mark_emitted(
        "run-123", "recovery_failed", first.claim_token
    ) is True

    third = store.claim("run-123", "recovery_failed", {"action_id": "a-1"})
    assert third.emitted is False
    assert third.claim_token == ""


def test_failed_audit_write_can_be_retried_after_lease(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(
        tmp_path / "audit.db",
        lease_seconds=1,
    )

    first = store.claim("run-123", "recovery_failed", {"action_id": "a-1"})
    assert first.emitted is True

    second = store.claim("run-123", "recovery_failed", {"action_id": "a-1"})
    assert second.emitted is False

    import time
    time.sleep(1.05)

    retry = store.claim("run-123", "recovery_failed", {"action_id": "a-1"})
    assert retry.emitted is True
    assert retry.claim_token
    assert retry.claim_token != first.claim_token


def test_mark_emitted_requires_current_claim(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    claim = store.claim("run-123", "recovery_failed", {"action_id": "a-1"})

    assert store.mark_emitted(
        "run-123", "recovery_failed", "wrong-token"
    ) is False

    assert store.mark_emitted(
        "run-123", "recovery_failed", claim.claim_token
    ) is True


def test_conflicting_pending_evidence_is_rejected(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    store.claim("run-123", "recovery_failed", {"action_id": "a-1"})

    with pytest.raises(ValueError, match="Conflicting audit evidence"):
        store.claim(
            "run-123",
            "recovery_failed",
            {"action_id": "a-2"},
        )


def test_second_process_can_observe_emitted_claim(tmp_path: Path):
    path = tmp_path / "audit.db"

    first_store = PersistentAuditIdempotencyStore(path)
    claim = first_store.claim(
        "run-123",
        "recovery_completed",
        {"action_id": "a-1"},
    )
    first_store.mark_emitted(
        "run-123",
        "recovery_completed",
        claim.claim_token,
    )

    second_store = PersistentAuditIdempotencyStore(path)
    result = second_store.claim(
        "run-123",
        "recovery_completed",
        {"action_id": "a-1"},
    )

    assert result.emitted is False
    assert second_store.contains("run-123", "recovery_completed") is True


def test_missing_claim_token_is_rejected(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    with pytest.raises(ValueError, match="claim_token is required"):
        store.mark_emitted("run-123", "recovery_failed", "")
