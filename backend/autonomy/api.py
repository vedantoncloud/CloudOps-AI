from dataclasses import asdict
from enum import Enum
from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from autonomy.action_models import ActionStatus
from autonomy.action_planner import ActionPlanner
from autonomy.approval import ApprovalManager
from autonomy.executor import ActionExecutor
from autonomy.policy_engine import PolicyEngine
from autonomy.recovery import RecoveryCoordinator
from autonomy.verifier import ActionVerifier
from autonomy.resource_inventory_api import _resource_tenant
from services.aws_service import AWSService


router = APIRouter(prefix="/autonomy", tags=["autonomy"])

aws_service = AWSService()
action_planner = ActionPlanner()
policy_engine = PolicyEngine()
approval_manager = ApprovalManager()
action_executor = ActionExecutor()
action_verifier = ActionVerifier()
recovery_coordinator = RecoveryCoordinator(verifier=action_verifier)

_plan_registry = {}
_plan_tenants = {}
_registry_lock = Lock()


def _serialize(value):
    if isinstance(value, Enum):
        return value.value

    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _serialize(item)
            for key, item in asdict(value).items()
        }

    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_serialize(item) for item in value]

    return value


def _store_plans(plans, tenant_id=None):
    with _registry_lock:
        for plan in plans:
            _plan_registry[plan.action_id] = plan
            _plan_tenants[plan.action_id] = tenant_id


def _get_plan(action_id: str, request: Request | None = None):
    with _registry_lock:
        plan = _plan_registry.get(action_id)
        if plan is None:
            return None
        if request is not None and getattr(request.state, "tenant_scoped", False):
            if _plan_tenants.get(action_id) != request.state.tenant_id:
                return None
        return plan


def _plan_response(plans, request: Request):
    tenant_id = request.state.tenant_id if getattr(request.state, "tenant_scoped", False) else None
    _store_plans(plans, tenant_id)
    return {
        "status": "healthy",
        "plan_count": len(plans),
        "plans": [_serialize(plan) for plan in plans],
    }


def _action_response(action):
    return {
        "status": "healthy",
        "action": _serialize(action),
    }


def _require_tenant_ec2_instance(request: Request, instance_id: str) -> None:
    """Keep plan generation inside the same ownership boundary as EC2 reads."""
    if not getattr(request.state, "tenant_scoped", False):
        return
    inventory = aws_service.get_ec2_instances()
    if inventory.get("status") != "healthy":
        raise HTTPException(status_code=503, detail="EC2 inventory is unavailable")
    tenant_id = request.state.tenant_id
    if not any(
        item.get("instance_id") == instance_id
        and _resource_tenant({"tags": item.get("tags", {})}) == tenant_id
        for item in inventory.get("instances", [])
    ):
        raise HTTPException(status_code=404, detail="EC2 instance not found")


def _require_tenant_s3_bucket(request: Request, bucket_name: str) -> None:
    """Fail closed when bucket ownership cannot be established."""
    if not getattr(request.state, "tenant_scoped", False):
        return
    ownership = aws_service.get_s3_bucket_tags(bucket_name)
    if (ownership.get("status") != "healthy"
            or _resource_tenant({"tags": ownership.get("tags", {})}) != request.state.tenant_id):
        raise HTTPException(status_code=404, detail="S3 bucket not found")


@router.post("/ec2/instances/{instance_id}/plans")
def plan_ec2_actions(instance_id: str, request: Request):
    _require_tenant_ec2_instance(request, instance_id)
    result = aws_service.get_ec2_insights(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(status_code=403, detail=result["error"])

    plans = action_planner.plan_from_ec2_insights(
        instance_id,
        result.get("insights", []),
    )

    return _plan_response(plans, request)


@router.post("/s3/buckets/{bucket_name}/plans")
def plan_s3_actions(
    request: Request,
    bucket_name: str,
    prefix: str | None = None,
    max_keys: int | None = None,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and not 1 <= max_keys <= 1000:
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_bucket_insights(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(status_code=403, detail=result["error"])

    plans = action_planner.plan_from_s3_insights(
        bucket_name,
        result.get("insights", []),
        prefix=prefix,
    )

    return _plan_response(plans, request)


@router.get("/plans")
def list_plans(request: Request, status: ActionStatus | None = None, limit: int = 50, offset: int = 0):
    """List plans available to this tenant, newest registry entries first."""
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")
    with _registry_lock:
        plans = [
            plan for action_id, plan in _plan_registry.items()
            if (not getattr(request.state, "tenant_scoped", False)
                or _plan_tenants.get(action_id) == request.state.tenant_id)
            and (status is None or plan.status == status)
        ]
    plans.reverse()
    total = len(plans)
    return {"plans": [_serialize(plan) for plan in plans[offset:offset + limit]],
            "total": total, "limit": limit, "offset": offset}


@router.get("/plans/{action_id}")
def get_plan(action_id: str, request: Request):
    """Return the current plan state, hiding plans owned by another tenant."""
    action = _get_plan(action_id, request)
    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")
    return _action_response(action)


@router.get("/approvals")
def list_pending_approvals(request: Request, limit: int = 50, offset: int = 0):
    """List the pending approval queue visible to this tenant."""
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")
    with _registry_lock:
        approvals = [
            plan for action_id, plan in _plan_registry.items()
            if plan.status == ActionStatus.PENDING_APPROVAL
            and (not getattr(request.state, "tenant_scoped", False)
                 or _plan_tenants.get(action_id) == request.state.tenant_id)
        ]
    approvals.reverse()
    total = len(approvals)
    return {
        "approvals": [_serialize(plan) for plan in approvals[offset:offset + limit]],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/plans/{action_id}/evaluate")
def evaluate_plan(action_id: str, request: Request):
    action = _get_plan(action_id, request)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    try:
        evaluated = policy_engine.evaluate(action)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _action_response(evaluated)


@router.post("/plans/{action_id}/approve")
def approve_plan(action_id: str, request: Request):
    action = _get_plan(action_id, request)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    try:
        principal = getattr(request.state, "principal", None)
        approved = approval_manager.approve(
            action, approved_by=getattr(principal, "subject", None)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _action_response(approved)


class RejectionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


@router.post("/plans/{action_id}/reject")
def reject_plan(action_id: str, payload: RejectionRequest, request: Request):
    action = _get_plan(action_id, request)
    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    principal = getattr(request.state, "principal", None)
    reviewer = getattr(principal, "subject", None)
    try:
        rejected = approval_manager.reject(action, reviewer, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_response(rejected)


@router.post("/plans/{action_id}/cancel")
def cancel_plan(action_id: str, request: Request):
    action = _get_plan(action_id, request)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    try:
        principal = getattr(request.state, "principal", None)
        cancelled = approval_manager.cancel(
            action, cancelled_by=getattr(principal, "subject", None)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _action_response(cancelled)


@router.post("/plans/{action_id}/execute")
def execute_plan(
    action_id: str,
    request: Request,
    dry_run: str = "true",
):
    action = _get_plan(action_id, request)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    normalized_dry_run = dry_run.strip().lower()

    if normalized_dry_run not in {"true", "false"}:
        raise HTTPException(
            status_code=400,
            detail="dry_run must be true or false",
        )

    if normalized_dry_run != "true":
        raise HTTPException(
            status_code=400,
            detail="Real infrastructure execution is disabled; use dry_run=true.",
        )

    if action.status != ActionStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail="Action must be approved before execution.",
        )

    try:
        execution_result = action_executor.execute(
            action,
            dry_run=True,
        )

        final_action = recovery_coordinator.verify_and_recover(
            action,
            execution_result,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "healthy",
        "action": _serialize(final_action),
        "execution": _serialize(execution_result),
    }

