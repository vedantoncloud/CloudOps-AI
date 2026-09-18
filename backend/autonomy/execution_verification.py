from dataclasses import dataclass, field
from typing import Any, Callable

from autonomy.action_models import ActionPlan, ActionStatus
from autonomy.audit import AuditTrail
from autonomy.executor import ActionExecutor, ExecutionResult
from autonomy.verifier import ActionVerifier


class VerificationOutcome(str):
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecutionVerificationResult:
    action_id: str
    old_status: str
    new_status: str
    execution_result: ExecutionResult
    verified: bool
    verification_outcome: str
    audit_event_count: int
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        return self.verified

    @property
    def requires_rollback(self) -> bool:
        return self.new_status == ActionStatus.ROLLBACK_REQUIRED.value


class ExecutionVerificationBridge:
    """Connect bounded execution, verification, and lifecycle auditing.

    The bridge reuses the existing ActionExecutor and ActionVerifier.
    Real infrastructure mutation remains disabled by ActionExecutor.
    """

    def __init__(
        self,
        *,
        executor: ActionExecutor | None = None,
        verifier: ActionVerifier | None = None,
        audit_trail: AuditTrail | None = None,
    ) -> None:
        self.executor = executor or ActionExecutor()
        self.verifier = verifier or ActionVerifier()
        self.audit_trail = audit_trail or AuditTrail()

    def execute_and_verify(
        self,
        action: ActionPlan,
        *,
        dry_run: bool = True,
        execution_hook: Callable[[ActionPlan, ExecutionResult], None] | None = None,
        verification_details: dict[str, Any] | None = None,
    ) -> ExecutionVerificationResult:
        self._validate_action(action)

        if action.status != ActionStatus.APPROVED:
            raise PermissionError(
                "Action must be approved before execution."
            )

        old_status = action.status.value

        execution_result = self.executor.execute(
            action,
            dry_run=dry_run,
        )

        # Validate identity before writing lifecycle audit events. This keeps
        # a mismatched executor result from being recorded as a valid event.
        self._validate_execution_result(action, execution_result)

        executing_status = action.status.value

        self.audit_trail.record(
            action_id=action.action_id,
            action_type=action.action_type,
            resource_type=action.target.resource_type,
            resource_id=action.target.resource_id,
            old_status=old_status,
            new_status=executing_status,
            event="action_execution_completed",
            details={
                "dry_run": execution_result.dry_run,
                "executed": execution_result.executed,
                "successful": execution_result.successful,
                "message": execution_result.message,
                **dict(execution_result.details),
            },
        )

        if execution_hook is not None:
            execution_hook(action, execution_result)

        verified_action = self.verifier.verify(
            action,
            execution_result,
        )

        new_status = verified_action.status.value
        verified = verified_action.status == ActionStatus.SUCCEEDED
        outcome = (
            VerificationOutcome.VERIFIED
            if verified
            else VerificationOutcome.FAILED
        )

        details = {
            "verification_outcome": outcome,
            "execution_successful": execution_result.successful,
            "dry_run": execution_result.dry_run,
            "executed": execution_result.executed,
        }

        if verification_details:
            details.update(verification_details)

        self.audit_trail.record(
            action_id=action.action_id,
            action_type=action.action_type,
            resource_type=action.target.resource_type,
            resource_id=action.target.resource_id,
            old_status=executing_status,
            new_status=new_status,
            event="action_verification_completed",
            details=details,
        )

        events = self.audit_trail.get_events(action.action_id)

        return ExecutionVerificationResult(
            action_id=action.action_id,
            old_status=old_status,
            new_status=new_status,
            execution_result=execution_result,
            verified=verified,
            verification_outcome=outcome,
            audit_event_count=len(events),
            evidence={
                "action_id": action.action_id,
                "action_type": action.action_type,
                "resource_type": action.target.resource_type,
                "resource_id": action.target.resource_id,
                "execution_status": executing_status,
                "verification_status": new_status,
                "verification_outcome": outcome,
                "dry_run": execution_result.dry_run,
                "executed": execution_result.executed,
                "execution_successful": execution_result.successful,
                "audit_event_count": len(events),
            },
        )

    def verify(
        self,
        action: ActionPlan,
        execution_result: ExecutionResult,
        *,
        verification_details: dict[str, Any] | None = None,
    ) -> ExecutionVerificationResult:
        """Verify an already completed execution result and audit it."""
        self._validate_action(action)
        self._validate_execution_result(action, execution_result)

        old_status = action.status.value

        verified_action = self.verifier.verify(
            action,
            execution_result,
        )

        new_status = verified_action.status.value
        verified = verified_action.status == ActionStatus.SUCCEEDED
        outcome = (
            VerificationOutcome.VERIFIED
            if verified
            else VerificationOutcome.FAILED
        )

        details = {
            "verification_outcome": outcome,
            "execution_successful": execution_result.successful,
            "dry_run": execution_result.dry_run,
            "executed": execution_result.executed,
        }

        if verification_details:
            details.update(verification_details)

        self.audit_trail.record(
            action_id=action.action_id,
            action_type=action.action_type,
            resource_type=action.target.resource_type,
            resource_id=action.target.resource_id,
            old_status=old_status,
            new_status=new_status,
            event="action_verification_completed",
            details=details,
        )

        events = self.audit_trail.get_events(action.action_id)

        return ExecutionVerificationResult(
            action_id=action.action_id,
            old_status=old_status,
            new_status=new_status,
            execution_result=execution_result,
            verified=verified,
            verification_outcome=outcome,
            audit_event_count=len(events),
            evidence={
                "action_id": action.action_id,
                "action_type": action.action_type,
                "resource_type": action.target.resource_type,
                "resource_id": action.target.resource_id,
                "execution_status": old_status,
                "verification_status": new_status,
                "verification_outcome": outcome,
                "dry_run": execution_result.dry_run,
                "executed": execution_result.executed,
                "execution_successful": execution_result.successful,
                "audit_event_count": len(events),
            },
        )

    def _validate_action(self, action: ActionPlan) -> None:
        if not action.action_id or not action.action_id.strip():
            raise ValueError("action_id cannot be empty")

        if not action.action_type or not action.action_type.strip():
            raise ValueError("action_type cannot be empty")

        if (
            not action.target.resource_type
            or not action.target.resource_type.strip()
        ):
            raise ValueError("resource_type cannot be empty")

        if (
            not action.target.resource_id
            or not action.target.resource_id.strip()
        ):
            raise ValueError("resource_id cannot be empty")

    @staticmethod
    def _validate_execution_result(
        action: ActionPlan,
        execution_result: ExecutionResult,
    ) -> None:
        if execution_result.action_id != action.action_id:
            raise ValueError(
                "Execution result does not match the action being verified."
            )
