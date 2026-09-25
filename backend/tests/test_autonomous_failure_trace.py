from types import SimpleNamespace

import pytest

from autonomy.autonomous_failure_trace import AutonomousFailureTraceBridge


def _run(run_id="run-001", outcome="failed"):
    return SimpleNamespace(
        run_id=run_id,
        outcome=outcome,
        execution_started=True,
        evidence={
            "run_id": run_id,
            "failure": {
                "stage": "autonomous_lifecycle",
                "exception_type": "RuntimeError",
            },
        },
    )


def _recovery(run_id="run-001", outcome="failed", failed=True, recovered=False):
    return SimpleNamespace(
        run_id=run_id,
        outcome=outcome,
        failed=failed,
        recovered=recovered,
        evidence={
            "run_id": run_id,
            "recovery_flow": outcome,
        },
    )


def test_failure_trace_preserves_same_run_id():
    result = AutonomousFailureTraceBridge().build(
        _run("run-101"),
        _recovery("run-101"),
    )

    assert result.run_id == "run-101"
    assert result.evidence["run_id"] == "run-101"
    assert result.evidence["trace"]["run_id"] == "run-101"


def test_failure_trace_preserves_run_and_recovery_evidence():
    result = AutonomousFailureTraceBridge().build(
        _run("run-102"),
        _recovery("run-102"),
    )

    assert result.evidence["run_evidence"]["failure"]["stage"] == "autonomous_lifecycle"
    assert result.evidence["recovery_evidence"]["recovery_flow"] == "failed"


def test_failed_recovery_produces_failed_final_outcome():
    result = AutonomousFailureTraceBridge().build(
        _run("run-103", outcome="completed"),
        _recovery("run-103", outcome="failed", failed=True),
    )

    assert result.outcome == "failed"
    assert result.failed is True


def test_failed_autonomous_run_remains_failed():
    result = AutonomousFailureTraceBridge().build(
        _run("run-104", outcome="failed"),
        _recovery("run-104", outcome="recovered", failed=False, recovered=True),
    )

    assert result.outcome == "failed"


def test_recovered_run_is_explicitly_recovered():
    result = AutonomousFailureTraceBridge().build(
        _run("run-105", outcome="completed"),
        _recovery("run-105", outcome="recovered", failed=False, recovered=True),
    )

    assert result.outcome == "recovered"
    assert result.failed is False


def test_mismatched_run_ids_are_rejected():
    with pytest.raises(ValueError, match="run_id mismatch"):
        AutonomousFailureTraceBridge().build(
            _run("run-a"),
            _recovery("run-b"),
        )
