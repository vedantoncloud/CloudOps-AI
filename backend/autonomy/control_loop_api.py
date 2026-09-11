from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.control_loop import AutonomousControlLoop
from autonomy.decision_intelligence import DecisionContext
from autonomy.gitops_api import registry as gitops_registry

router = APIRouter(
    prefix="/autonomy/control-loop",
    tags=["autonomy-control-loop"],
)


class ControlLoopEvaluateRequest(BaseModel):
    action_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = True
    field: str = Field(min_length=1)
    desired_value: Any = None
    current_value: Any | None = None


class ControlLoopEvaluateResponse(BaseModel):
    action_id: str
    resource_id: str
    recommendation: str
    risk: str
    confidence: float
    preventive: bool
    requires_human_review: bool
    blocked: bool
    gitops_created: bool
    gitops_change_id: str | None
    gitops_status: str | None
    reasons: list[str]
    evidence: dict[str, Any]


@router.post("/evaluate", response_model=ControlLoopEvaluateResponse)
def evaluate_control_loop(
    request: ControlLoopEvaluateRequest,
) -> ControlLoopEvaluateResponse:
    try:
        action = ActionPlan(
            action_id=request.action_id,
            action_type=request.action_type,
            target=ActionTarget(
                resource_type=request.resource_type,
                resource_id=request.resource_id,
            ),
            reason=request.reason,
            risk=request.risk,
            requires_approval=request.requires_approval,
            status=ActionStatus.PENDING_APPROVAL,
        )

        context = DecisionContext(
            resource_id=request.resource_id,
            resource_type=request.resource_type,
            action=action,
        )

        result = AutonomousControlLoop().evaluate(
            action=action,
            decision_context=context,
            field=request.field,
            desired_value=request.desired_value,
            current_value=request.current_value,
        )

        gitops_change_id = None
        gitops_status = None
        gitops_created = False

        if result.gitops is not None:
            gitops_created = result.gitops.created

            if result.gitops.change_set is not None:
                change_set = result.gitops.change_set
                existing = gitops_registry.get(change_set.change_id)

                if existing is None:
                    existing = gitops_registry.register(change_set)

                gitops_change_id = existing.change_id
                gitops_status = existing.status.value

        return ControlLoopEvaluateResponse(
            action_id=result.action.action_id,
            resource_id=result.action.target.resource_id,
            recommendation=result.decision.recommendation.value,
            risk=result.decision.risk.value,
            confidence=result.decision.confidence,
            preventive=result.decision.preventive,
            requires_human_review=result.decision.requires_human_review,
            blocked=result.blocked,
            gitops_created=gitops_created,
            gitops_change_id=gitops_change_id,
            gitops_status=gitops_status,
            reasons=result.decision.reasons,
            evidence=result.decision.evidence,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
