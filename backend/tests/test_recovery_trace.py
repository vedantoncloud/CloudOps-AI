from types import SimpleNamespace

import pytest

from autonomy.action_models import ActionStatus
from autonomy.reliable_recovery import ReliableRecoveryBoundary
from autonomy.recovery_trace import RecoveryTraceBridge


class SuccessfulRecovery:
    def recover(self, action, execution_result, *, rollback_successful=True, run_id=None):
        return SimpleNamespace(
            outcome="recovered",
            failed=False,
            evidence={
                "recovery_flow": "recovered",
                "run_id": run_id,
            },
        )


class FailedRecovery:
    def recover(self, action, execution_result, *, rollback_successful=True, run_id=None):
        return SimpleNamespace(
            outcome="failed",
            failed=True,
            evidence={
                "recovery_flow": "failed",
                "run_id": run_id,
                "failure": {
                    "stage": "verification_or_recovery",
                    "exception_type": "RuntimeError",
                },
            },
        )


def _action():
    return SimpleNamespace(
        action_id="action-trace-001",
        status=ActionStatus.FAILED,
    )


def test_recovery_trace_preserves_run_id():
    result = RecoveryTraceBridge(SuccessfulRecovery()).recover(
        "run-trace-001",
        _action(),
        SimpleNamespace(),
    )

    assert result.run_id == "run-trace-001"
    assert result.evidence["run_id"] == "run-trace-001"
    assert result.evidence["trace"]["run_id"] == "run-trace-001"


def test_recovery_trace_preserves_recovery_outcome():
    result = RecoveryTraceBridge(SuccessfulRecovery()).recover(
        "run-trace-002",
        _action(),
        SimpleNamespace(),
    )

    assert result.outcome == "recovered"
    assert result.failed is False
    assert result.evidence["trace"]["recovery_outcome"] == "recovered"


def test_failed_recovery_remains_failed_and_traceable():
    result = RecoveryTraceBridge(FailedRecovery()).recover(
        "run-trace-003",
        _action(),
        SimpleNamespace(),
    )

    assert result.outcome == "failed"
    assert result.failed is True
    assert result.evidence["run_id"] == "run-trace-003"
    assert result.evidence["failure"]["stage"] == "verification_or_recovery"


def test_run_id_is_required():
    with pytest.raises(ValueError, match="run_id is required"):
        RecoveryTraceBridge(SuccessfulRecovery()).recover(
            "",
            _action(),
            SimpleNamespace(),
        )


def test_trace_contains_action_identity():
    result = RecoveryTraceBridge(SuccessfulRecovery()).recover(
        "run-trace-004",
        _action(),
        SimpleNamespace(),
    )

    assert result.evidence["trace"]["action_id"] == "action-trace-001"
