from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.action_models import ActionPlan, ActionStatus
from autonomy.executor import ExecutionResult
from autonomy.recovery import RecoveryCoordinator
from autonomy.rollback import RollbackResult


@dataclass(frozen=True)
class RecoveryOutcome:
    outcome: str
    action: ActionPlan
    rollback: RollbackResult | None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def recovered(self) -> bool:
        return self.outcome == "recovered"

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"


class ReliableRecoveryBoundary:
    """Make verification/recovery failures explicit without automatic retries."""

    def __init__(self, coordinator: RecoveryCoordinator | None = None) -> None:
        self.coordinator = coordinator or RecoveryCoordinator()

    def recover(
        self,
        action: ActionPlan,
        execution_result: ExecutionResult,
        *,
        rollback_successful: bool = True,
        run_id: str | None = None,
    ) -> RecoveryOutcome:
        trace_id = (run_id or "").strip() or None
        try:
            recovered_action = self.coordinator.verify_and_recover(
                action,
                execution_result,
                rollback_successful=rollback_successful,
            )
        except Exception as exc:
            evidence = {
                "recovery_flow": "failed",
                "failure": {
                    "stage": "verification_or_recovery",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                },
                "action_id": getattr(action, "action_id", None),
                "action_status": getattr(getattr(action, "status", None), "value", getattr(action, "status", None)),
            }
            if trace_id is not None:
                evidence["run_id"] = trace_id
            return RecoveryOutcome("failed", action, None, evidence)

        status = getattr(recovered_action, "status", None)
        status_value = getattr(status, "value", status)
        if status == ActionStatus.ROLLED_BACK:
            outcome = "recovered"
        elif status == ActionStatus.FAILED:
            outcome = "failed"
        else:
            outcome = "completed"

        evidence = {
            "recovery_flow": outcome,
            "action_id": getattr(recovered_action, "action_id", None),
            "action_status": status_value,
            "rollback_required": status == ActionStatus.ROLLBACK_REQUIRED,
        }
        if trace_id is not None:
            evidence["run_id"] = trace_id
        return RecoveryOutcome(outcome, recovered_action, None, evidence)
