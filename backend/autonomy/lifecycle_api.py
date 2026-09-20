from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.autonomous_lifecycle import (
    AutonomousLifecycleOrchestrator,
    AutonomousLifecycleResult,
)


router = APIRouter(
    prefix="/autonomy/lifecycle",
    tags=["autonomous-lifecycle"],
)

orchestrator = AutonomousLifecycleOrchestrator()


class LifecycleActionRequest(BaseModel):
    action_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk: str = "low"
    requires_approval: bool = True
    rollback_available: bool = True
    dry_run: bool = True
    idempotency_key: str | None = None
    idempotency_seen: bool = False


class LifecycleRunRequest(LifecycleActionRequest):
    approved_by: str | None = None


class LifecycleApproveRequest(LifecycleActionRequest):
    approved_by: str = Field(min_length=1)


class LifecycleRejectRequest(LifecycleActionRequest):
    rejected_by: str = Field(min_length=1)
    rejection_reason: str = Field(min_length=1)


def _risk(value: str) -> RiskLevel:
    try:
        return RiskLevel(value.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid risk level: {value}",
        ) from exc


def _action(payload: LifecycleActionRequest) -> ActionPlan:
    return ActionPlan(
        action_type=payload.action_type.strip(),
        target=ActionTarget(
            resource_type=payload.resource_type.strip(),
            resource_id=payload.resource_id.strip(),
        ),
        reason=payload.reason.strip(),
        risk=_risk(payload.risk),
        requires_approval=payload.requires_approval,
        rollback_available=payload.rollback_available,
        status=(
            ActionStatus.APPROVED
            if getattr(payload, "approved_by", None)
            else ActionStatus.PENDING_APPROVAL
        ),
        action_id=payload.action_id.strip(),
    )


def _result(result: AutonomousLifecycleResult) -> dict[str, Any]:
    execution = result.execution
    verification = result.verification

    return {
        "action_id": result.action_id,
        "outcome": result.outcome,
        "completed": result.completed,
        "blocked": result.blocked,
        "requires_human_approval": result.requires_human_approval,
        "approval": {
            "status": result.approval.status.value,
            "approved_by": result.approval.approved_by,
            "rejected_by": result.approval.evidence.get("rejected_by"),
            "reason": result.approval.rejection_reason,
            "evidence": dict(result.approval.evidence),
        },
        "safety": {
            "decision": result.safety.decision.value,
            "execution_allowed": result.safety.execution_allowed,
            "requires_human_approval": result.safety.requires_human_approval,
            "dry_run": result.safety.dry_run,
            "destructive": result.safety.destructive,
            "reasons": list(result.safety.reasons),
            "evidence": dict(result.safety.evidence),
        },
        "execution": (
            None
            if execution is None
            else {
                "action_id": execution.action_id,
                "status": execution.status.value,
                "dry_run": execution.dry_run,
                "executed": execution.executed,
                "successful": execution.successful,
                "message": execution.message,
                "details": dict(execution.details),
            }
        ),
        "verification": (
            None
            if verification is None
            else {
                "verified": verification.verified,
                "outcome": verification.verification_outcome,
                "new_status": verification.new_status,
                "evidence": dict(verification.evidence),
            }
        ),
        "evidence": dict(result.evidence),
    }


@router.post("/run")
def run_lifecycle(payload: LifecycleRunRequest) -> dict[str, Any]:
    try:
        action = _action(payload)
        result = orchestrator.run(
            action,
            approved_by=payload.approved_by,
            idempotency_key=payload.idempotency_key,
            idempotency_seen=payload.idempotency_seen,
            dry_run=(payload.dry_run if payload.approved_by else False),
        )
        return _result(result)
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approve")
def approve_lifecycle(payload: LifecycleApproveRequest) -> dict[str, Any]:
    try:
        action = _action(payload)
        result = orchestrator.approve_and_run(
            action,
            approved_by=payload.approved_by,
            idempotency_key=payload.idempotency_key,
            idempotency_seen=payload.idempotency_seen,
            dry_run=payload.dry_run,
        )
        return _result(result)
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reject")
def reject_lifecycle(payload: LifecycleRejectRequest) -> dict[str, Any]:
    try:
        action = _action(payload)
        result = orchestrator.reject(
            action,
            rejected_by=payload.rejected_by,
            reason=payload.rejection_reason,
            dry_run=False,
        )
        return _result(result)
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{action_id}/audit")
def get_lifecycle_audit(action_id: str) -> dict[str, Any]:
    if not action_id.strip():
        raise HTTPException(status_code=400, detail="action_id cannot be empty")

    events = orchestrator.audit_events(action_id.strip())
    return {
        "action_id": action_id.strip(),
        "count": len(events),
        "events": [
            {
                "action_id": event.action_id,
                "action_type": event.action_type,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "old_status": event.old_status,
                "new_status": event.new_status,
                "event": event.event,
                "timestamp": event.timestamp,
                "details": dict(event.details),
            }
            for event in events
        ],
    }
