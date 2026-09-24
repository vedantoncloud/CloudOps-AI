from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.governed_autonomous_run import GovernedAutonomousRun, GovernedAutonomousRunResult


router = APIRouter(
    prefix="/autonomy",
    tags=["autonomous-run"],
)

runner = GovernedAutonomousRun()


class AutonomousRunRequest(BaseModel):
    provider: str = Field(default="aws", min_length=1)
    action_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = True
    rollback_available: bool = True
    approved_by: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    idempotency_key: str | None = None
    idempotency_seen: bool = False
    dry_run: bool = True


def _action(payload: AutonomousRunRequest) -> ActionPlan:
    return ActionPlan(
        action_type=payload.action_type.strip(),
        target=ActionTarget(
            resource_type=payload.resource_type.strip(),
            resource_id=payload.resource_id.strip(),
        ),
        reason=payload.reason.strip(),
        risk=payload.risk,
        requires_approval=payload.requires_approval,
        rollback_available=payload.rollback_available,
        status=ActionStatus.PENDING_APPROVAL,
        action_id=payload.action_id.strip(),
    )


def _result(result: GovernedAutonomousRunResult) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "outcome": result.outcome,
            "execution_started": result.execution_started,
            "blocked": result.blocked,
            "requires_human_review": result.requires_human_review,
            "completed": result.completed,
            "governance": result.governance,
            "lifecycle": result.lifecycle,
            "evidence": dict(result.evidence),
        }
    )


@router.post("/run")
def run_autonomous(payload: AutonomousRunRequest) -> dict[str, Any]:
    try:
        action = _action(payload)
        result = runner.run(
            provider=payload.provider.strip(),
            action=action,
            resource_type=payload.resource_type.strip(),
            resource_id=payload.resource_id.strip(),
            approved_by=payload.approved_by,
            rejected_by=payload.rejected_by,
            rejection_reason=payload.rejection_reason,
            idempotency_key=payload.idempotency_key,
            idempotency_seen=payload.idempotency_seen,
            dry_run=payload.dry_run,
        )
        return _result(result)
    except (ValueError, PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
