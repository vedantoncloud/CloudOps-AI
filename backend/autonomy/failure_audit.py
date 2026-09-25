from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.audit import AuditTrail
from autonomy.autonomous_failure_trace import AutonomousFailureTrace


@dataclass(frozen=True)
class FailureAuditResult:
    """Result of emitting a failure/recovery trace into the audit trail."""

    run_id: str
    events: tuple[str, ...]
    evidence: dict[str, Any] = field(default_factory=dict)


class FailureAuditBridge:
    """Persist autonomous failure/recovery evidence through the existing AuditTrail.

    This bridge emits structured, append-only audit events only. It performs no
    retries and no infrastructure mutation.
    """

    def __init__(self, audit_trail: AuditTrail | None = None) -> None:
        self.audit_trail = audit_trail or AuditTrail()

    def record(self, trace: AutonomousFailureTrace) -> FailureAuditResult:
        run_id = (trace.run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required for failure audit traceability")

        evidence = dict(trace.evidence)
        evidence["run_id"] = run_id
        evidence["outcome"] = trace.outcome

        events: list[str] = []

        run_event = "autonomous_run_failed" if trace.outcome == "failed" else "autonomous_run_recovery_completed"
        self._record(run_event, evidence)
        events.append(run_event)

        recovery_outcome = evidence.get("recovery_outcome")
        if recovery_outcome in {"failed", "recovered", "completed"}:
            recovery_event = (
                "recovery_failed"
                if recovery_outcome == "failed"
                else "recovery_completed"
            )
            recovery_evidence = {
                "run_id": run_id,
                "outcome": recovery_outcome,
                "action_id": self._action_id(evidence),
                "trace": evidence.get("trace", {}),
                "recovery_evidence": evidence.get("recovery_evidence", {}),
            }
            self._record(recovery_event, recovery_evidence)
            events.append(recovery_event)

        return FailureAuditResult(run_id, tuple(events), evidence)

    @staticmethod
    def _action_id(evidence: dict[str, Any]) -> str | None:
        recovery_evidence = evidence.get("recovery_evidence")
        if isinstance(recovery_evidence, dict):
            value = recovery_evidence.get("action_id")
            if value:
                return str(value)

        trace = evidence.get("trace")
        if isinstance(trace, dict):
            value = trace.get("action_id")
            if value:
                return str(value)

        return None

    def _record(self, event_type: str, evidence: dict[str, Any]) -> None:
        """Use the existing AuditTrail contract without adding a second audit store."""
        self.audit_trail.record(event_type, evidence)
