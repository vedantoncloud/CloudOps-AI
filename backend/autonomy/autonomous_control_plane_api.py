"""FastAPI surface for the unified autonomous control plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.autonomous_control_plane import AutonomousControlPlane
from autonomy.provider import CloudProvider


router = APIRouter(
    prefix="/autonomy/control-plane",
    tags=["autonomous-control-plane"],
)

control_plane = AutonomousControlPlane()


class ReadOnlyAPIProvider(CloudProvider):
    """Provider-neutral dry-run adapter for the API surface."""

    @property
    def provider_name(self) -> str:
        return "aws"

    def get_ec2_instances(
        self,
        state: str | None = None,
        tag_filter: str | None = None,
    ) -> dict[str, Any]:
        return {"resources": [], "read_only": True}

    def get_ec2_summary(self) -> dict[str, Any]:
        return {"count": 0, "read_only": True}

    def get_s3_buckets(self) -> dict[str, Any]:
        return {"resources": [], "read_only": True}


_provider_registry: dict[str, CloudProvider] = {
    "aws": ReadOnlyAPIProvider(),
}


class ControlPlaneRunRequest(BaseModel):
    provider: str = "aws"
    resource_type: str
    resource_id: str
    action_type: str
    reason: str = "Autonomous control-plane request"
    risk: str = "medium"
    target: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    idempotency_key: str | None = None
    idempotency_seen: bool = False
    dry_run: bool = True


def _risk(value: str) -> RiskLevel:
    try:
        return RiskLevel(value.strip().lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid risk: {value}") from exc


def _target(payload: ControlPlaneRunRequest) -> ActionTarget:
    return ActionTarget(
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
    )


def _action(payload: ControlPlaneRunRequest) -> ActionPlan:
    return ActionPlan(
        action_id=f"api-{payload.resource_type}-{payload.resource_id}",
        action_type=payload.action_type,
        target=_target(payload),
        reason=payload.reason.strip() or "Autonomous control-plane request",
        risk=_risk(payload.risk),
        status=ActionStatus.PENDING_APPROVAL,
    )


def _provider(name: str) -> CloudProvider:
    provider = _provider_registry.get(name.strip().lower())
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {name}")
    return provider


@router.post("/run")
def run_control_plane(payload: ControlPlaneRunRequest) -> dict[str, Any]:
    try:
        action = _action(payload)

        result = control_plane.run(
            provider=_provider(payload.provider),
            action=action,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            approved_by=payload.approved_by,
            rejected_by=payload.rejected_by,
            rejection_reason=payload.rejection_reason,
            idempotency_key=payload.idempotency_key,
            idempotency_seen=payload.idempotency_seen,
            dry_run=payload.dry_run,
        )

        return {
            "action_id": action.action_id,
            "outcome": result.outcome,
            "executed": result.executed,
            "governed": result.governed.evidence,
            "lifecycle": (
                None if result.lifecycle is None else result.lifecycle.evidence
            ),
            "evidence": result.evidence,
        }
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
