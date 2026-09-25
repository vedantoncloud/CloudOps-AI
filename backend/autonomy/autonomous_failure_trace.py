from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.governed_autonomous_run import GovernedAutonomousRunResult
from autonomy.recovery_trace import RecoveryTraceResult


@dataclass(frozen=True)
class AutonomousFailureTrace:
    """Join autonomous-run and recovery evidence under one correlation ID."""

    run_id: str
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"


class AutonomousFailureTraceBridge:
    """Build a single trace from an autonomous run and its recovery result.

    This is an evidence/integration boundary only. It performs no retry and no
    infrastructure mutation.
    """

    def build(
        self,
        run: GovernedAutonomousRunResult,
        recovery: RecoveryTraceResult,
    ) -> AutonomousFailureTrace:
        if run.run_id != recovery.run_id:
            raise ValueError("run_id mismatch between autonomous run and recovery")

        evidence = {
            "run_id": run.run_id,
            "run_outcome": run.outcome,
            "lifecycle_started": run.execution_started,
            "run_evidence": dict(run.evidence),
            "recovery_outcome": recovery.outcome,
            "recovery_evidence": dict(recovery.evidence),
            "trace": {
                "run_id": run.run_id,
                "run_outcome": run.outcome,
                "recovery_outcome": recovery.outcome,
            },
        }

        if run.outcome == "failed" or recovery.failed:
            outcome = "failed"
        elif recovery.recovered:
            outcome = "recovered"
        else:
            outcome = recovery.outcome

        return AutonomousFailureTrace(
            run_id=run.run_id,
            outcome=outcome,
            evidence=evidence,
        )
