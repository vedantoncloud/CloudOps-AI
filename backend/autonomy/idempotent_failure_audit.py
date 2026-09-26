from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from autonomy.audit import AuditTrail
from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.failure_audit import FailureAuditBridge


@dataclass(frozen=True)
class IdempotentFailureAuditResult:
    run_id: str
    emitted_events: tuple[str, ...]
    skipped_events: tuple[str, ...]
    evidence: dict[str, Any] = field(default_factory=dict)


class IdempotentFailureAuditBridge(FailureAuditBridge):
    """Prevent duplicate failure/recovery audit events within one process."""

    def __init__(self, audit_trail: AuditTrail | None = None) -> None:
        super().__init__(audit_trail)
        self._emitted: dict[tuple[str, str], dict[str, Any]] = {}

    def record(self, trace: AutonomousFailureTrace) -> IdempotentFailureAuditResult:
        run_id = (trace.run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required for failure audit traceability")

        evidence = dict(trace.evidence)
        evidence["run_id"] = run_id
        evidence["outcome"] = trace.outcome

        candidates: list[tuple[str, dict[str, Any]]] = []
        run_event = (
            "autonomous_run_failed"
            if trace.outcome == "failed"
            else "autonomous_run_recovery_completed"
        )
        candidates.append((run_event, evidence))

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
            candidates.append((recovery_event, recovery_evidence))

        emitted: list[str] = []
        skipped: list[str] = []
        for event_type, event_evidence in candidates:
            key = (run_id, event_type)
            if key in self._emitted:
                previous = self._emitted[key]
                if previous != event_evidence:
                    raise ValueError("Conflicting audit evidence")
                skipped.append(event_type)
                continue
            self._record(event_type, event_evidence)
            self._emitted[key] = dict(event_evidence)
            emitted.append(event_type)

        return IdempotentFailureAuditResult(
            run_id, tuple(emitted), tuple(skipped), evidence
        )




