from __future__ import annotations

from typing import Any
from threading import RLock

from fastapi import APIRouter, HTTPException, Request
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
_action_owners: dict[str, str] = {}
_owner_lock = RLock()


def _actor(request: Request, supplied: str | None = None) -> str:
    principal = getattr(request.state, "principal", None)
    return principal.subject if principal is not None else (supplied or "local-development")


def _scope(request: Request, actor: str) -> str:
    return request.state.tenant_id if getattr(request.state, "tenant_scoped", False) else actor


def _claim_action(action_id: str, scope: str, *, create: bool = True) -> None:
    with _owner_lock:
        owner = _action_owners.get(action_id)
        if owner is not None and owner != scope:
            raise HTTPException(status_code=404, detail="Lifecycle action not found")
        if owner is None:
            if not create:
                raise HTTPException(status_code=404, detail="Lifecycle action not found")
            _action_owners[action_id] = scope


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
def run_lifecycle(payload: LifecycleRunRequest, request: Request) -> dict[str, Any]:
    try:
        actor = _actor(request, payload.approved_by)
        tenant_id = request.state.tenant_id if getattr(request.state, "tenant_scoped", False) else None
        if getattr(request.state, "principal", None) is not None and payload.approved_by:
            payload = payload.model_copy(update={"approved_by": actor})
        action = _action(payload)
        _claim_action(action.action_id, _scope(request, actor))
        result = orchestrator.run(
            action,
            approved_by=payload.approved_by,
            idempotency_key=payload.idempotency_key,
            idempotency_seen=payload.idempotency_seen,
            dry_run=(payload.dry_run if payload.approved_by else False),
            actor_id=actor,
            tenant_id=tenant_id,
        )
        return _result(result)
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approve")
def approve_lifecycle(payload: LifecycleApproveRequest, request: Request) -> dict[str, Any]:
    try:
        actor = _actor(request, payload.approved_by)
        if getattr(request.state, "principal", None) is not None:
            payload = payload.model_copy(update={"approved_by": actor})
        action = _action(payload)
        _claim_action(action.action_id, _scope(request, actor))
        result = orchestrator.approve_and_run(
            action,
            approved_by=payload.approved_by,
            idempotency_key=payload.idempotency_key,
            idempotency_seen=payload.idempotency_seen,
            dry_run=payload.dry_run,
            actor_id=actor,
        )
        return _result(result)
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reject")
def reject_lifecycle(payload: LifecycleRejectRequest, request: Request) -> dict[str, Any]:
    try:
        actor = _actor(request, payload.rejected_by)
        tenant_id = request.state.tenant_id if getattr(request.state, "tenant_scoped", False) else None
        if getattr(request.state, "principal", None) is not None:
            payload = payload.model_copy(update={"rejected_by": actor})
        action = _action(payload)
        _claim_action(action.action_id, _scope(request, actor))
        result = orchestrator.reject(
            action,
            rejected_by=payload.rejected_by,
            reason=payload.rejection_reason,
            dry_run=False,
            actor_id=actor,
        )
        return _result(result)
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{action_id}/audit")
def get_lifecycle_audit(action_id: str, request: Request) -> dict[str, Any]:
    if not action_id.strip():
        raise HTTPException(status_code=400, detail="action_id cannot be empty")

    audit_actor = _actor(request)
    audit_scope = (
        _scope(request, audit_actor)
        if getattr(request.state, "tenant_scoped", False)
        else _action_owners.get(action_id.strip())
    )
    _claim_action(action_id.strip(), audit_scope or audit_actor, create=False)
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
                "actor_id": event.actor_id,
                "details": dict(event.details),
            }
            for event in events
        ],
    }
