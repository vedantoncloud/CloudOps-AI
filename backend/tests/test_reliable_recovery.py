from types import SimpleNamespace

from autonomy.action_models import ActionStatus
from autonomy.recovery import RecoveryCoordinator
from autonomy.reliable_recovery import ReliableRecoveryBoundary


class FailingCoordinator:
    def verify_and_recover(self, action, execution_result, *, rollback_successful=True):
        raise RuntimeError("recovery unavailable")


class CompletedCoordinator:
    def verify_and_recover(self, action, execution_result, *, rollback_successful=True):
        action.status = "completed"
        return action


def test_recovery_exception_becomes_explicit_failure():
    action = SimpleNamespace(action_id="action-001", status=ActionStatus.FAILED)
    result = ReliableRecoveryBoundary(FailingCoordinator()).recover(
        action, SimpleNamespace(), run_id="run-001"
    )
    assert result.outcome == "failed"
    assert result.failed is True
    assert result.evidence["run_id"] == "run-001"
    assert result.evidence["failure"]["stage"] == "verification_or_recovery"
    assert result.evidence["failure"]["exception_type"] == "RuntimeError"


def test_recovery_does_not_retry():
    calls = {"count": 0}

    class CountingCoordinator:
        def verify_and_recover(self, action, execution_result, *, rollback_successful=True):
            calls["count"] += 1
            raise RuntimeError("one attempt")

    result = ReliableRecoveryBoundary(CountingCoordinator()).recover(
        SimpleNamespace(action_id="a", status=ActionStatus.FAILED),
        SimpleNamespace(),
    )
    assert result.failed is True
    assert calls["count"] == 1


def test_successful_recovery_boundary_preserves_completed_state():
    action = SimpleNamespace(action_id="action-002", status=ActionStatus.FAILED)
    result = ReliableRecoveryBoundary(CompletedCoordinator()).recover(
        action, SimpleNamespace(), run_id="run-002"
    )
    assert result.outcome == "completed"
    assert result.action.status == "completed"
    assert result.evidence["run_id"] == "run-002"
    assert result.evidence["action_id"] == "action-002"


def test_existing_recovery_coordinator_remains_usable():
    boundary = ReliableRecoveryBoundary(RecoveryCoordinator())
    assert boundary.coordinator is not None
