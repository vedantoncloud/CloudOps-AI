from __future__ import annotations

from pathlib import Path

import pytest

from autonomy.audit import AuditTrail
from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.idempotent_failure_audit import IdempotentFailureAuditBridge
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def trace(
    *,
    run_id: str = "run-123",
    outcome: str = "failed",
    action_id: str = "action-1",
    recovery: str = "failed",
) -> AutonomousFailureTrace:
    return AutonomousFailureTrace(
        run_id=run_id,
        outcome=outcome,
        evidence={
            "run_id": run_id,
            "recovery_outcome": recovery,
            "recovery_evidence": {"action_id": action_id},
            "trace": {
                "run_id": run_id,
                "run_outcome": outcome,
                "recovery_outcome": recovery,
                "action_id": action_id,
            },
        },
    )


def test_persistent_store_deduplicates_across_bridge_instances(tmp_path: Path):
    path = tmp_path / "audit.db"

    first_audit = AuditTrail()
    first = IdempotentFailureAuditBridge(
        first_audit,
        PersistentAuditIdempotencyStore(path),
    )
    first_result = first.record(trace())

    second_audit = AuditTrail()
    second = IdempotentFailureAuditBridge(
        second_audit,
        PersistentAuditIdempotencyStore(path),
    )
    second_result = second.record(trace())

    assert first_result.emitted_events == (
        "autonomous_run_failed",
        "recovery_failed",
    )
    assert second_result.emitted_events == ()
    assert second_result.skipped_events == (
        "autonomous_run_failed",
        "recovery_failed",
    )


def test_persistent_store_preserves_conflict_detection(tmp_path: Path):
    path = tmp_path / "audit.db"

    bridge = IdempotentFailureAuditBridge(
        AuditTrail(),
        PersistentAuditIdempotencyStore(path),
    )
    bridge.record(trace(action_id="action-1"))

    with pytest.raises(ValueError, match="Conflicting audit evidence"):
        bridge.record(trace(action_id="action-2"))


def test_without_store_keeps_existing_in_memory_behavior():
    bridge = IdempotentFailureAuditBridge(AuditTrail())

    first = bridge.record(trace())
    second = bridge.record(trace())

    assert first.emitted_events == (
        "autonomous_run_failed",
        "recovery_failed",
    )
    assert second.emitted_events == ()
    assert second.skipped_events == (
        "autonomous_run_failed",
        "recovery_failed",
    )


def test_missing_run_id_does_not_touch_persistent_store(tmp_path: Path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)
    bridge = IdempotentFailureAuditBridge(AuditTrail(), store)

    with pytest.raises(ValueError, match="run_id is required"):
        bridge.record(trace(run_id=""))

    assert store.contains("run-123", "autonomous_run_failed") is False
