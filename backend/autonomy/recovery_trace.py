from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.action_models import ActionPlan
from autonomy.executor import ExecutionResult
from autonomy.reliable_recovery import RecoveryOutcome, ReliableRecoveryBoundary


@dataclass(frozen=True)
class RecoveryTraceResult:
    run_id: str
    recovery: RecoveryOutcome
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        return self.recovery.outcome

    @property
    def failed(self) -> bool:
        return self.recovery.failed


class RecoveryTraceBridge:
    """Attach an autonomous run trace ID to an existing recovery boundary."""

    def __init__(
        self,
        recovery: ReliableRecoveryBoundary | None = None,
    ) -> None:
        self.recovery = recovery or ReliableRecoveryBoundary()

    def recover(
        self,
        run_id: str,
        action: ActionPlan,
        execution_result: ExecutionResult,
        *,
        rollback_successful: bool = True,
    ) -> RecoveryTraceResult:
        trace_id = (run_id or "").strip()
        if not trace_id:
            raise ValueError("run_id is required for recovery traceability")

        recovery_result = self.recovery.recover(
            action,
            execution_result,
            rollback_successful=rollback_successful,
            run_id=trace_id,
        )

        evidence = dict(recovery_result.evidence)
        evidence["run_id"] = trace_id
        evidence["trace"] = {
            "run_id": trace_id,
            "recovery_outcome": recovery_result.outcome,
            "action_id": getattr(action, "action_id", None),
            "action_status": getattr(
                getattr(action, "status", None),
                "value",
                getattr(action, "status", None),
            ),
        }

        return RecoveryTraceResult(
            run_id=trace_id,
            recovery=recovery_result,
            evidence=evidence,
        )
