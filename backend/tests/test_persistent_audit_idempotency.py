from __future__ import annotations

from pathlib import Path

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_first_claim_is_emitted(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    result = store.claim(
        "run-123",
        "recovery_failed",
        {"action_id": "action-1", "outcome": "failed"},
    )

    assert result.emitted is True
    assert result.run_id == "run-123"
    assert result.event_type == "recovery_failed"


def test_same_claim_is_skipped(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    evidence = {"action_id": "action-1", "outcome": "failed"}

    first = store.claim("run-123", "recovery_failed", evidence)
    second = store.claim("run-123", "recovery_failed", evidence)

    assert first.emitted is True
    assert second.emitted is False


def test_conflicting_claim_is_rejected(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    store.claim("run-123", "recovery_failed", {"action_id": "action-1"})

    with pytest.raises(ValueError, match="Conflicting audit evidence"):
        store.claim("run-123", "recovery_failed", {"action_id": "action-2"})


def test_different_event_types_can_be_claimed(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    first = store.claim("run-123", "autonomous_run_failed", {"outcome": "failed"})
    second = store.claim("run-123", "recovery_failed", {"outcome": "failed"})

    assert first.emitted is True
    assert second.emitted is True


def test_different_store_instance_sees_existing_claim(tmp_path: Path):
    path = tmp_path / "audit.db"

    first_store = PersistentAuditIdempotencyStore(path)
    first_store.claim("run-123", "recovery_completed", {"action_id": "action-1"})

    second_store = PersistentAuditIdempotencyStore(path)
    result = second_store.claim(
        "run-123",
        "recovery_completed",
        {"action_id": "action-1"},
    )

    assert result.emitted is False
    assert second_store.contains("run-123", "recovery_completed") is True


def test_missing_identifiers_are_rejected(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    with pytest.raises(ValueError, match="run_id is required"):
        store.claim("", "recovery_failed", {})

    with pytest.raises(ValueError, match="event_type is required"):
        store.claim("run-123", "", {})
