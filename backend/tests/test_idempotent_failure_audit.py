from __future__ import annotations

import pytest

from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.idempotent_failure_audit import IdempotentFailureAuditBridge


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


def test_first_record_emits_both_events():
    audit = FakeAuditTrail()
    result = IdempotentFailureAuditBridge(audit).record(make_trace())
    assert result.emitted_events == ("autonomous_run_failed", "recovery_failed")
    assert result.skipped_events == ()
    assert len(audit.events) == 2


def test_repeated_record_skips_duplicate_events():
    audit = FakeAuditTrail()
    bridge = IdempotentFailureAuditBridge(audit)
    bridge.record(make_trace())
    result = bridge.record(make_trace())
    assert result.emitted_events == ()
    assert result.skipped_events == ("autonomous_run_failed", "recovery_failed")
    assert len(audit.events) == 2


def test_different_run_ids_are_not_deduplicated():
    audit = FakeAuditTrail()
    bridge = IdempotentFailureAuditBridge(audit)
    bridge.record(make_trace())
    trace = make_trace()
    trace = AutonomousFailureTrace("run-456", trace.outcome, {**trace.evidence, "run_id": "run-456"})
    result = bridge.record(trace)
    assert result.emitted_events == ("autonomous_run_failed", "recovery_failed")
    assert len(audit.events) == 4


def test_failed_write_remains_retryable():
    audit = FakeAuditTrail(fail_on_call=2)
    bridge = IdempotentFailureAuditBridge(audit)
    with pytest.raises(RuntimeError, match="audit write failed"):
        bridge.record(make_trace())
    assert [event[0] for event in audit.events] == ["autonomous_run_failed"]
    result = bridge.record(make_trace())
    assert result.emitted_events == ("recovery_failed",)
    assert result.skipped_events == ("autonomous_run_failed",)
    assert [event[0] for event in audit.events] == ["autonomous_run_failed", "recovery_failed"]


def test_missing_recovery_event_is_idempotent():
    audit = FakeAuditTrail()
    bridge = IdempotentFailureAuditBridge(audit)
    trace = AutonomousFailureTrace("run-123", "failed", {"run_id": "run-123", "recovery_outcome": None})
    first = bridge.record(trace)
    second = bridge.record(trace)
    assert first.emitted_events == ("autonomous_run_failed",)
    assert second.emitted_events == ()
    assert second.skipped_events == ("autonomous_run_failed",)


def test_requires_run_id():
    with pytest.raises(ValueError, match="run_id is required"):
        IdempotentFailureAuditBridge(FakeAuditTrail()).record(
            AutonomousFailureTrace("", "failed", {})
        )


def test_preserves_trace_and_action_evidence():
    audit = FakeAuditTrail()
    result = IdempotentFailureAuditBridge(audit).record(make_trace())
    assert result.evidence["trace"]["action_id"] == "action-456"
    assert audit.events[1][1]["action_id"] == "action-456"
