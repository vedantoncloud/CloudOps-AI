from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autonomy.action_models import ActionPlan, ActionStatus
from autonomy.approval_execution import (
    ApprovalExecutionBridge,
    ApprovalRecord,
    ApprovalStatus,
)
from autonomy.audit import AuditTrail
from autonomy.execution_safety import (
    ExecutionSafetyDecision,
    ExecutionSafetyResult,
)
from autonomy.execution_verification import (
    ExecutionVerificationBridge,
    ExecutionVerificationResult,
)


class LifecycleOutcome(str):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class AutonomousLifecycleResult:
    action_id: str
    outcome: str
    approval: ApprovalRecord
    safety: ExecutionSafetyResult
    execution: Any | None = None
    verification: ExecutionVerificationResult | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def completed(self) -> bool:
        return self.outcome == LifecycleOutcome.COMPLETED

    @property
    def blocked(self) -> bool:
        return self.outcome == LifecycleOutcome.BLOCKED

    @property
    def requires_human_approval(self) -> bool:
        return self.outcome == LifecycleOutcome.AWAITING_APPROVAL


class AutonomousLifecycleOrchestrator:
    """End-to-end bounded action lifecycle.

    This orchestrator connects the existing safety, approval, execution,
    verification, and audit components. It deliberately does not implement
    cloud-provider mutations itself.
    """

    def __init__(
        self,
        *,
        approval_bridge: ApprovalExecutionBridge | None = None,
        verification_bridge: ExecutionVerificationBridge | None = None,
        audit_trail: AuditTrail | None = None,
    ) -> None:
        self.audit_trail = audit_trail or AuditTrail()
        self.approval_bridge = approval_bridge or ApprovalExecutionBridge()
        self.verification_bridge = (
            verification_bridge
            or ExecutionVerificationBridge(audit_trail=self.audit_trail)
        )

    def run(
        self,
        action: ActionPlan,
        *,
        approved_by: str | None = None,
        rejected_by: str | None = None,
        rejection_reason: str | None = None,
        decision: Any = None,
        blast_radius: Any = None,
        idempotency_key: str | None = None,
        idempotency_seen: bool = False,
        dry_run: bool = True,
    ) -> AutonomousLifecycleResult:
        self._validate_action(action)

        self._audit(
            action,
            old_status=action.status.value,
            new_status=action.status.value,
            event="autonomous_lifecycle_started",
            details={
                "dry_run": dry_run,
                "idempotency_key": idempotency_key,
                "idempotency_seen": idempotency_seen,
            },
        )

        approval = self.approval_bridge.get(action.action_id)
        if approval is None:
            approval = self.approval_bridge.submit(action)

        if rejected_by is not None:
            if rejection_reason is None:
                raise ValueError("rejection_reason is required when rejecting.")
            approval = self.approval_bridge.reject(
                action,
                rejected_by=rejected_by,
                reason=rejection_reason,
            )

        if approved_by is not None:
            approval = self.approval_bridge.approve(
                action,
                approved_by=approved_by,
            )

        approval_result = self.approval_bridge.execute(
            action,
            decision=decision,
            blast_radius=blast_radius,
            idempotency_key=idempotency_key,
            idempotency_seen=idempotency_seen,
            dry_run=dry_run,
        )

        safety = approval_result.safety

        self._audit(
            action,
            old_status=action.status.value,
            new_status=action.status.value,
            event="autonomous_safety_evaluated",
            details={
                "safety_decision": safety.decision.value,
                "execution_allowed": safety.execution_allowed,
                "requires_human_approval": safety.requires_human_approval,
                "approval_status": approval.status.value,
                "safety_evidence": dict(safety.evidence),
            },
        )

        if safety.decision is ExecutionSafetyDecision.DENY:
            self._audit(
                action,
                old_status=action.status.value,
                new_status=action.status.value,
                event="autonomous_lifecycle_blocked",
                details={"reason": "execution_safety_denied"},
            )
            return AutonomousLifecycleResult(
                action_id=action.action_id,
                outcome=LifecycleOutcome.BLOCKED,
                approval=approval,
                safety=safety,
                evidence=self._evidence(
                    action,
                    outcome=LifecycleOutcome.BLOCKED,
                    approval=approval,
                    safety=safety,
                ),
            )

        if not approval_result.executed:
            outcome = (
                LifecycleOutcome.AWAITING_APPROVAL
                if safety.requires_human_approval
                or approval.status is ApprovalStatus.PENDING
                else LifecycleOutcome.BLOCKED
            )
            self._audit(
                action,
                old_status=action.status.value,
                new_status=action.status.value,
                event="autonomous_lifecycle_waiting",
                details={
                    "outcome": outcome,
                    "approval_status": approval.status.value,
                },
            )
            return AutonomousLifecycleResult(
                action_id=action.action_id,
                outcome=outcome,
                approval=approval,
                safety=safety,
                evidence=self._evidence(
                    action,
                    outcome=outcome,
                    approval=approval,
                    safety=safety,
                ),
            )

        execution_result = approval_result.execution_result
        if execution_result is None:
            raise RuntimeError(
                "Execution was reported as successful but no execution result was returned."
            )

        verification = self.verification_bridge.verify(
            action,
            execution_result,
            verification_details={
                "lifecycle": "autonomous_lifecycle",
                "approval_status": approval.status.value,
                "approved_by": approval.approved_by,
                "safety_decision": safety.decision.value,
            },
        )

        outcome = (
            LifecycleOutcome.COMPLETED
            if verification.verified
            else LifecycleOutcome.FAILED
        )

        self._audit(
            action,
            old_status=verification.new_status,
            new_status=verification.new_status,
            event="autonomous_lifecycle_completed",
            details={
                "outcome": outcome,
                "verification_outcome": verification.verification_outcome,
                "audit_event_count": verification.audit_event_count,
            },
        )

        return AutonomousLifecycleResult(
            action_id=action.action_id,
            outcome=outcome,
            approval=approval,
            safety=safety,
            execution=execution_result,
            verification=verification,
            evidence={
                **self._evidence(
                    action,
                    outcome=outcome,
                    approval=approval,
                    safety=safety,
                ),
                "execution": {
                    "executed": execution_result.executed,
                    "successful": execution_result.successful,
                    "dry_run": execution_result.dry_run,
                    "message": execution_result.message,
                },
                "verification": dict(verification.evidence),
                "audit_event_count": len(
                    self.audit_trail.get_events(action.action_id)
                ),
            },
        )

    def approve_and_run(
        self,
        action: ActionPlan,
        *,
        approved_by: str,
        decision: Any = None,
        blast_radius: Any = None,
        idempotency_key: str | None = None,
        idempotency_seen: bool = False,
        dry_run: bool = True,
    ) -> AutonomousLifecycleResult:
        return self.run(
            action,
            approved_by=approved_by,
            decision=decision,
            blast_radius=blast_radius,
            idempotency_key=idempotency_key,
            idempotency_seen=idempotency_seen,
            dry_run=dry_run,
        )

    def reject(
        self,
        action: ActionPlan,
        *,
        rejected_by: str,
        reason: str,
        dry_run: bool = True,
    ) -> AutonomousLifecycleResult:
        return self.run(
            action,
            rejected_by=rejected_by,
            rejection_reason=reason,
            dry_run=dry_run,
        )

    def audit_events(self, action_id: str) -> list[Any]:
        return self.audit_trail.get_events(action_id)

    @staticmethod
    def _validate_action(action: ActionPlan) -> None:
        if not str(getattr(action, "action_id", "")).strip():
            raise ValueError("action_id cannot be empty")
        if not str(getattr(action, "action_type", "")).strip():
            raise ValueError("action_type cannot be empty")
        target = getattr(action, "target", None)
        if target is None:
            raise ValueError("action target is required")
        if not str(getattr(target, "resource_type", "")).strip():
            raise ValueError("resource_type cannot be empty")
        if not str(getattr(target, "resource_id", "")).strip():
            raise ValueError("resource_id cannot be empty")

    def _audit(
        self,
        action: ActionPlan,
        *,
        old_status: str,
        new_status: str,
        event: str,
        details: dict[str, Any],
    ) -> None:
        self.audit_trail.record(
            action_id=action.action_id,
            action_type=action.action_type,
            resource_type=action.target.resource_type,
            resource_id=action.target.resource_id,
            old_status=old_status,
            new_status=new_status,
            event=event,
            details=details,
        )

    @staticmethod
    def _evidence(
        action: ActionPlan,
        *,
        outcome: str,
        approval: ApprovalRecord,
        safety: ExecutionSafetyResult,
    ) -> dict[str, Any]:
        return {
            "action_id": action.action_id,
            "action_type": action.action_type,
            "resource_type": action.target.resource_type,
            "resource_id": action.target.resource_id,
            "outcome": outcome,
            "approval_status": approval.status.value,
            "approved_by": approval.approved_by,
            "safety_decision": safety.decision.value,
            "execution_allowed": safety.execution_allowed,
            "requires_human_approval": safety.requires_human_approval,
            "approval_evidence": dict(approval.evidence),
            "safety_evidence": dict(safety.evidence),
        }
