from __future__ import annotations

from types import SimpleNamespace

import pytest

from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.failure_audit import FailureAuditBridge


class FakeAuditTrail:
    def __init__(self):
        self.events = []

    def record(self, event_type, evidence):
        self.events.append((event_type, dict(evidence)))


def make_trace(outcome="failed"):
    return AutonomousFailureTrace(
        run_id="run-123",
        outcome=outcome,
        evidence={
            "run_id": "run-123",
            "run_outcome": "failed",
            "lifecycle_started": True,
            "recovery_outcome": "failed" if outcome == "failed" else "recovered",
            "trace": {
                "run_id": "run-123",
                "run_outcome": "failed",
                "recovery_outcome": "failed" if outcome == "failed" else "recovered",
            },
            "recovery_evidence": {
                "action_id": "action-456",
                "action_status": "failed",
            },
        },
    )


def test_records_failed_run_and_recovery():
    audit = FakeAuditTrail()
    result = FailureAuditBridge(audit).record(make_trace("failed"))

    assert result.run_id == "run-123"
    assert result.events == (
        "autonomous_run_failed",
        "recovery_failed",
    )
    assert [event[0] for event in audit.events] == [
        "autonomous_run_failed",
        "recovery_failed",
    ]
    assert audit.events[0][1]["run_id"] == "run-123"
    assert audit.events[1][1]["action_id"] == "action-456"


def test_records_recovered_run():
    audit = FakeAuditTrail()
    result = FailureAuditBridge(audit).record(make_trace("recovered"))

    assert result.events == (
        "autonomous_run_recovery_completed",
        "recovery_completed",
    )
    assert audit.events[1][1]["outcome"] == "recovered"


def test_preserves_trace_evidence():
    audit = FakeAuditTrail()
    result = FailureAuditBridge(audit).record(make_trace())

    assert result.evidence["trace"]["run_id"] == "run-123"
    assert result.evidence["recovery_evidence"]["action_id"] == "action-456"


def test_requires_run_id():
    audit = FakeAuditTrail()
    trace = AutonomousFailureTrace(run_id="", outcome="failed", evidence={})

    with pytest.raises(ValueError, match="run_id is required"):
        FailureAuditBridge(audit).record(trace)


def test_does_not_emit_recovery_event_when_recovery_outcome_missing():
    audit = FakeAuditTrail()
    trace = AutonomousFailureTrace(
        run_id="run-123",
        outcome="failed",
        evidence={"run_id": "run-123", "recovery_outcome": None},
    )

    result = FailureAuditBridge(audit).record(trace)

    assert result.events == ("autonomous_run_failed",)
    assert len(audit.events) == 1


def test_uses_trace_action_id_as_fallback():
    audit = FakeAuditTrail()
    trace = AutonomousFailureTrace(
        run_id="run-123",
        outcome="failed",
        evidence={
            "recovery_outcome": "failed",
            "trace": {"run_id": "run-123", "action_id": "action-789"},
        },
    )

    FailureAuditBridge(audit).record(trace)

    assert audit.events[1][1]["action_id"] == "action-789"
