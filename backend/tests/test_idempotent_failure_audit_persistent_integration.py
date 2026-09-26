from __future__ import annotations

from pathlib import Path

from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.idempotent_failure_audit import IdempotentFailureAuditBridge
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


class FakeAuditTrail:
    def __init__(self, fail_on_call=None):
        self.events = []
        self.fail_on_call = fail_on_call
        self.calls = 0

    def record(self, event_type, evidence):
        self.calls += 1
        if self.fail_on_call == self.calls:
            self.fail_on_call = None
            raise RuntimeError("audit write failed")
        self.events.append((event_type, dict(evidence)))


def make_trace():
    return AutonomousFailureTrace(
        run_id="run-123",
        outcome="failed",
        evidence={
            "run_id": "run-123",
            "recovery_outcome": "failed",
            "trace": {"run_id": "run-123", "action_id": "action-456"},
            "recovery_evidence": {"action_id": "action-456"},
        },
    )


def test_success_marks_both_persistent_claims_emitted(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    audit = FakeAuditTrail()

    result = IdempotentFailureAuditBridge(
        audit,
        idempotency_store=store,
    ).record(make_trace())

    assert result.emitted_events == (
        "autonomous_run_failed",
        "recovery_failed",
    )
    assert store.claim(
        "run-123",
        "autonomous_run_failed",
        result.evidence,
    ).emitted is False


def test_failed_second_write_leaves_second_claim_retryable(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(
        tmp_path / "audit.db",
        lease_seconds=1,
    )
    audit = FakeAuditTrail(fail_on_call=2)
    bridge = IdempotentFailureAuditBridge(
        audit,
        idempotency_store=store,
    )

    import pytest

    with pytest.raises(RuntimeError, match="audit write failed"):
        bridge.record(make_trace())

    assert [event[0] for event in audit.events] == [
        "autonomous_run_failed"
    ]

    # The first event is durably emitted; the second remains pending.
    assert store.claim(
        "run-123",
        "autonomous_run_failed",
        make_trace().evidence | {
            "run_id": "run-123",
            "outcome": "failed",
        },
    ).emitted is False

    import time
    time.sleep(1.05)

    retry = IdempotentFailureAuditBridge(
        audit,
        idempotency_store=store,
    ).record(make_trace())

    assert retry.emitted_events == ("recovery_failed",)
    assert retry.skipped_events == ("autonomous_run_failed",)


def test_persistent_store_survives_new_bridge_instance(tmp_path: Path):
    store_path = tmp_path / "audit.db"
    audit = FakeAuditTrail()

    first = IdempotentFailureAuditBridge(
        audit,
        idempotency_store=PersistentAuditIdempotencyStore(store_path),
    )
    first_result = first.record(make_trace())

    second = IdempotentFailureAuditBridge(
        audit,
        idempotency_store=PersistentAuditIdempotencyStore(store_path),
    )
    second_result = second.record(make_trace())

    assert first_result.emitted_events == (
        "autonomous_run_failed",
        "recovery_failed",
    )
    assert second_result.emitted_events == ()
    assert second_result.skipped_events == (
        "autonomous_run_failed",
        "recovery_failed",
    )
    assert len(audit.events) == 2


def test_mark_failure_does_not_duplicate_audit_event(tmp_path: Path, monkeypatch):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    audit = FakeAuditTrail()

    original = store.mark_emitted

    def fail_mark(run_id, event_type, claim_token):
        if event_type == "recovery_failed":
            return False
        return original(run_id, event_type, claim_token)

    monkeypatch.setattr(store, "mark_emitted", fail_mark)

    import pytest

    with pytest.raises(
        RuntimeError,
        match="could not be marked emitted",
    ):
        IdempotentFailureAuditBridge(
            audit,
            idempotency_store=store,
        ).record(make_trace())

    assert [event[0] for event in audit.events] == [
        "autonomous_run_failed",
        "recovery_failed",
    ]
