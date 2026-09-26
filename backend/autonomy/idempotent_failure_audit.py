from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.audit import AuditTrail
from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


@dataclass(frozen=True)
class IdempotentFailureAuditResult:
    run_id: str
    emitted_events: tuple[str, ...]
    skipped_events: tuple[str, ...]
    evidence: dict[str, Any] = field(default_factory=dict)


class IdempotentFailureAuditBridge:
    def __init__(
        self,
        audit_trail: AuditTrail | None = None,
        idempotency_store: PersistentAuditIdempotencyStore | None = None,
    ):
        self.audit_trail = audit_trail or AuditTrail()
        self.idempotency_store = idempotency_store
        self._emitted: dict[tuple[str, str], dict[str, Any]] = {}

    def record(self, trace: AutonomousFailureTrace) -> IdempotentFailureAuditResult:
        run_id = (trace.run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")

        evidence = dict(trace.evidence)
        evidence["run_id"] = run_id
        evidence["outcome"] = trace.outcome

        emitted: list[str] = []
        skipped: list[str] = []

        for event_type, event_evidence in self._events_for_trace(
            trace,
            evidence,
        ):
            key = (run_id, event_type)

            if self.idempotency_store is not None:
                claim = self.idempotency_store.claim(
                    run_id,
                    event_type,
                    event_evidence,
                )
                if not claim.emitted:
                    skipped.append(event_type)
                    continue
            else:
                previous = self._emitted.get(key)
                if previous is not None:
                    if previous != event_evidence:
                        raise ValueError("Conflicting audit evidence")
                    skipped.append(event_type)
                    continue
                claim = None

            audit_kwargs = self._audit_kwargs(event_type, event_evidence)
            try:
                self._record_audit_event(
                    event_type,
                    event_evidence,
                    audit_kwargs,
                )
            except Exception:
                # A persistent claim remains pending. The store's lease allows
                # a later process/run to reclaim it after the audit write fails.
                raise

            if self.idempotency_store is not None:
                marked = self.idempotency_store.mark_emitted(
                    run_id,
                    event_type,
                    claim.claim_token,
                )
                if not marked:
                    raise RuntimeError(
                        "Persistent audit claim could not be marked emitted"
                    )
            else:
                self._emitted[key] = dict(event_evidence)

            emitted.append(event_type)

        return IdempotentFailureAuditResult(
            run_id=run_id,
            emitted_events=tuple(emitted),
            skipped_events=tuple(skipped),
            evidence=evidence,
        )

    def _record_audit_event(
        self,
        event_type: str,
        evidence: dict[str, Any],
        audit_kwargs: dict[str, Any],
    ) -> None:
        if isinstance(self.audit_trail, AuditTrail):
            self.audit_trail.record(**audit_kwargs)
            return

        self.audit_trail.record(event_type, dict(evidence))

    @staticmethod
    def _audit_kwargs(
        event_type: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        recovery_evidence = evidence.get("recovery_evidence")
        if not isinstance(recovery_evidence, dict):
            recovery_evidence = {}

        trace = evidence.get("trace")
        if not isinstance(trace, dict):
            trace = {}

        action_id = (
            recovery_evidence.get("action_id")
            or trace.get("action_id")
            or evidence.get("action_id")
            or f"audit-{evidence['run_id']}"
        )

        return {
            "action_id": action_id,
            "action_type": (
                recovery_evidence.get("action_type")
                or evidence.get("action_type")
                or "autonomous_failure_recovery"
            ),
            "resource_type": (
                recovery_evidence.get("resource_type")
                or evidence.get("resource_type")
                or "autonomous_run"
            ),
            "resource_id": (
                recovery_evidence.get("resource_id")
                or evidence.get("resource_id")
                or evidence["run_id"]
            ),
            "old_status": (
                recovery_evidence.get("old_status")
                or "unknown"
            ),
            "new_status": (
                recovery_evidence.get("new_status")
                or evidence.get("outcome")
                or "unknown"
            ),
            "event": event_type,
            "details": dict(evidence),
        }

    @staticmethod
    def _events_for_trace(
        trace: AutonomousFailureTrace,
        evidence: dict[str, Any],
    ) -> list[tuple[str, dict[str, Any]]]:
        run_event = (
            "autonomous_run_failed"
            if trace.outcome == "failed"
            else "autonomous_run_recovery_completed"
        )

        events: list[tuple[str, dict[str, Any]]] = [
            (run_event, dict(evidence)),
        ]

        recovery_outcome = evidence.get("recovery_outcome")
        if recovery_outcome in {"failed", "recovered", "completed"}:
            recovery_event = (
                "recovery_failed"
                if recovery_outcome == "failed"
                else "recovery_completed"
            )
            recovery_evidence = {
                "run_id": evidence["run_id"],
                "outcome": recovery_outcome,
                "action_id": IdempotentFailureAuditBridge._action_id(evidence),
                "trace": evidence.get("trace", {}),
                "recovery_evidence": evidence.get(
                    "recovery_evidence",
                    {},
                ),
            }
            events.append((recovery_event, recovery_evidence))

        return events

    @staticmethod
    def _action_id(evidence: dict[str, Any]) -> str | None:
        recovery_evidence = evidence.get("recovery_evidence")
        if isinstance(recovery_evidence, dict):
            action_id = recovery_evidence.get("action_id")
            if action_id:
                return action_id

        trace = evidence.get("trace")
        if isinstance(trace, dict):
            action_id = trace.get("action_id")
            if action_id:
                return action_id

        return evidence.get("action_id")
