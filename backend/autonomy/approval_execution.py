from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from threading import RLock
from typing import Any, Callable

from autonomy.action_models import ActionPlan, ActionStatus
from autonomy.execution_safety import (
    ExecutionSafetyDecision,
    ExecutionSafetyGate,
    ExecutionSafetyResult,
)


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ApprovalRecord:
    action_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    rejection_reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalExecutionResult:
    action_id: str
    approval: ApprovalRecord
    safety: ExecutionSafetyResult
    executed: bool
    execution_result: Any | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.safety.decision is ExecutionSafetyDecision.DENY

    @property
    def requires_human_approval(self) -> bool:
        return self.safety.requires_human_approval


class ApprovalExecutionBridge:
    """Human-approval boundary between execution safety and the existing executor.

    The bridge never performs cloud mutations itself. It delegates only an
    approved ActionPlan to the injected executor. Dry-run remains the default.
    """

    def __init__(
        self,
        *,
        safety_gate: ExecutionSafetyGate | None = None,
        executor: Any | None = None,
        executor_factory: Callable[[], Any] | None = None,
    ) -> None:
        if executor is not None and executor_factory is not None:
            raise ValueError("Provide executor or executor_factory, not both.")

        self.safety_gate = safety_gate or ExecutionSafetyGate()
        self._executor = executor
        self._executor_factory = executor_factory
        self._approvals: dict[str, ApprovalRecord] = {}
        self._lock = RLock()

    def submit(self, action: ActionPlan) -> ApprovalRecord:
        action_id = self._action_id(action)
        if not action_id:
            raise ValueError("action_id cannot be empty")

        with self._lock:
            existing = self._approvals.get(action_id)
            if existing is not None:
                return existing

            record = ApprovalRecord(
                action_id=action_id,
                evidence={
                    "action_id": action_id,
                    "action_type": str(action.action_type),
                    "resource_id": action.target.resource_id,
                    "status": ApprovalStatus.PENDING.value,
                },
            )
            self._approvals[action_id] = record
            return record

    def get(self, action_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._approvals.get(str(action_id).strip())

    def approve(self, action: ActionPlan, *, approved_by: str) -> ApprovalRecord:
        action_id = self._action_id(action)
        approver = str(approved_by).strip()
        if not action_id:
            raise ValueError("action_id cannot be empty")
        if not approver:
            raise ValueError("approved_by cannot be empty")

        with self._lock:
            current = self._approvals.get(action_id)
            if current is not None and current.status is ApprovalStatus.REJECTED:
                raise ValueError("Rejected actions cannot be approved.")
            if current is not None and current.status is ApprovalStatus.APPROVED:
                return current

            record = ApprovalRecord(
                action_id=action_id,
                status=ApprovalStatus.APPROVED,
                approved_by=approver,
                evidence={
                    "action_id": action_id,
                    "approved_by": approver,
                    "approval_status": ApprovalStatus.APPROVED.value,
                },
            )
            self._approvals[action_id] = record
            return record

    def reject(self, action: ActionPlan, *, rejected_by: str, reason: str) -> ApprovalRecord:
        action_id = self._action_id(action)
        rejector = str(rejected_by).strip()
        rejection_reason = str(reason).strip()

        if not action_id:
            raise ValueError("action_id cannot be empty")
        if not rejector:
            raise ValueError("rejected_by cannot be empty")
        if not rejection_reason:
            raise ValueError("reason cannot be empty")

        with self._lock:
            current = self._approvals.get(action_id)
            if current is not None and current.status is ApprovalStatus.APPROVED:
                raise ValueError("Approved actions cannot be rejected.")

            record = ApprovalRecord(
                action_id=action_id,
                status=ApprovalStatus.REJECTED,
                rejection_reason=rejection_reason,
                evidence={
                    "action_id": action_id,
                    "rejected_by": rejector,
                    "rejection_reason": rejection_reason,
                    "approval_status": ApprovalStatus.REJECTED.value,
                },
            )
            self._approvals[action_id] = record
            return record

    def execute(
        self,
        action: ActionPlan,
        *,
        decision: Any = None,
        blast_radius: Any = None,
        idempotency_key: str | None = None,
        idempotency_seen: bool = False,
        dry_run: bool = True,
    ) -> ApprovalExecutionResult:
        action_id = self._action_id(action)
        if not action_id:
            raise ValueError("action_id cannot be empty")

        approval = self.get(action_id) or self.submit(action)
        explicit_approval = approval.status is ApprovalStatus.APPROVED

        safety = self.safety_gate.evaluate(
            action,
            decision=decision,
            blast_radius=blast_radius,
            idempotency_key=idempotency_key,
            idempotency_seen=idempotency_seen,
            approved=explicit_approval,
            dry_run=dry_run,
        )

        evidence = {
            "action_id": action_id,
            "approval_status": approval.status.value,
            "approved_by": approval.approved_by,
            "dry_run": dry_run,
            "safety_decision": safety.decision.value,
            "execution_allowed": safety.execution_allowed,
            "requires_human_approval": safety.requires_human_approval,
            "approval_evidence": dict(approval.evidence),
            "safety_evidence": dict(safety.evidence),
        }

        if not safety.execution_allowed:
            return ApprovalExecutionResult(
                action_id=action_id,
                approval=approval,
                safety=safety,
                executed=False,
                evidence=evidence,
            )

        if not dry_run and approval.status is not ApprovalStatus.APPROVED:
            return ApprovalExecutionResult(
                action_id=action_id,
                approval=approval,
                safety=self.safety_gate.evaluate(
                    action,
                    decision="review",
                    approved=False,
                    dry_run=False,
                ),
                executed=False,
                evidence=evidence,
            )

        approved_action = action
        if not dry_run and getattr(action, "status", None) is not ActionStatus.APPROVED:
            approved_action = replace(action, status=ActionStatus.APPROVED)

        execution_result = self._get_executor().execute(
            approved_action,
            dry_run=dry_run,
        )

        evidence["executor_invoked"] = True
        return ApprovalExecutionResult(
            action_id=action_id,
            approval=approval,
            safety=safety,
            executed=True,
            execution_result=execution_result,
            evidence=evidence,
        )

    def can_execute(self, action: ActionPlan, *, dry_run: bool = True) -> bool:
        result = self.execute(action, dry_run=dry_run)
        return result.executed

    def clear(self) -> None:
        with self._lock:
            self._approvals.clear()

    def _get_executor(self) -> Any:
        if self._executor is not None:
            return self._executor
        if self._executor_factory is not None:
            return self._executor_factory()

        from autonomy.executor import ActionExecutor

        return ActionExecutor()

    @staticmethod
    def _action_id(action: ActionPlan) -> str:
        return str(getattr(action, "action_id", "")).strip()
