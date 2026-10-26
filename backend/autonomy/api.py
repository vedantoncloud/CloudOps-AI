from dataclasses import asdict
from datetime import datetime
from enum import Enum
from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from autonomy.action_models import ActionPlan, ActionStatus, RiskLevel
from autonomy.action_planner import ActionPlanner
from autonomy.audit_api import audit_trail
from autonomy.approval import ApprovalManager
from autonomy.executor import ActionExecutor
from autonomy.policy_engine import PolicyEngine
from autonomy.recovery import RecoveryCoordinator
from autonomy.verifier import ActionVerifier
from autonomy.resource_inventory_api import _resource_tenant
from autonomy.action_plan_store import ActionPlanStore
import re
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
action_plan_store = ActionPlanStore()
for _stored_plan, _stored_tenant in action_plan_store.load_all():
    _plan_registry[_stored_plan.action_id] = _stored_plan
    _plan_tenants[_stored_plan.action_id] = _stored_tenant


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
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
        action_plan_store.save_many(plans, tenant_id)
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


def _persist_plan(plan: ActionPlan) -> None:
    with _registry_lock:
        action_plan_store.save_many(
            [plan], _plan_tenants.get(plan.action_id)
        )


def _plan_response(plans, request: Request):
    tenant_id = request.state.tenant_id if getattr(request.state, "tenant_scoped", False) else None
    principal = getattr(request.state, "principal", None)
    actor_id = getattr(principal, "subject", None)
    for plan in plans:
        audit_trail.record(
            action_id=plan.action_id,
            action_type=plan.action_type,
            resource_type=plan.target.resource_type,
            resource_id=plan.target.resource_id,
            old_status="none",
            new_status=plan.status.value,
            event="plan_created",
            actor_id=actor_id,
            details={"tenant_id": tenant_id} if tenant_id is not None else {},
        )
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


def _load_action_insights(provider_call):
    """Read a validated insight payload or fail closed on provider problems."""
    try:
        result = provider_call()
    except Exception:
        raise HTTPException(
            status_code=503, detail="AWS resource data is unavailable"
        ) from None
    if (not isinstance(result, dict)
            or result.get("status") != "healthy"
            or not isinstance(result.get("insights"), list)):
        raise HTTPException(
            status_code=503, detail="AWS resource data is unavailable"
        )
    return result["insights"]


def _record_plan_transition(action: ActionPlan, request: Request, old_status: ActionStatus) -> None:
    """Persist an attributed audit event for a lifecycle decision."""
    principal = getattr(request.state, "principal", None)
    tenant_id = request.state.tenant_id if getattr(request.state, "tenant_scoped", False) else None
    event = f"plan_{action.status.value}"
    audit_trail.record(
        action_id=action.action_id,
        action_type=action.action_type,
        resource_type=action.target.resource_type,
        resource_id=action.target.resource_id,
        old_status=old_status.value,
        new_status=action.status.value,
        event=event,
        actor_id=getattr(principal, "subject", None),
        details={"tenant_id": tenant_id} if tenant_id is not None else {},
    )


def _require_tenant_ec2_instance(request: Request, instance_id: str, region: str | None = None) -> None:
    """Keep plan generation inside the same ownership boundary as EC2 reads."""
    if not getattr(request.state, "tenant_scoped", False):
        return
    try:
        result = aws_service.get_ec2_instance(
            instance_id, **({"region": region} if region else {})
        )
    except Exception:
        raise HTTPException(
            status_code=503, detail="AWS resource data is unavailable"
        ) from None
    if not isinstance(result, dict) or result.get("status") != "healthy":
        raise HTTPException(status_code=503, detail="EC2 inventory is unavailable")
    instance = result.get("instance")
    if instance is None:
        raise HTTPException(status_code=404, detail="EC2 instance not found")
    tags = instance.get("tags") if isinstance(instance, dict) else None
    if (
        not isinstance(instance, dict)
        or instance.get("instance_id") != instance_id
        or not isinstance(tags, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in tags.items())
    ):
        raise HTTPException(status_code=503, detail="EC2 inventory is unavailable")
    if _resource_tenant({"tags": tags}) != request.state.tenant_id:
        raise HTTPException(status_code=404, detail="EC2 instance not found")


def _require_tenant_s3_bucket(request: Request, bucket_name: str) -> None:
    """Fail closed when bucket ownership cannot be established."""
    if not getattr(request.state, "tenant_scoped", False):
        return
    try:
        ownership = aws_service.get_s3_bucket_tags(bucket_name)
    except Exception:
        raise HTTPException(
            status_code=503, detail="S3 ownership verification is unavailable"
        ) from None
    if not isinstance(ownership, dict):
        raise HTTPException(status_code=503, detail="S3 ownership verification is unavailable")
    if ownership.get("status") == "missing":
        raise HTTPException(status_code=404, detail="S3 bucket not found")
    tags = ownership.get("tags")
    if (
        ownership.get("status") != "healthy"
        or (ownership.get("bucket") is not None and ownership.get("bucket") != bucket_name)
        or not isinstance(tags, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in tags.items())
    ):
        raise HTTPException(status_code=503, detail="S3 ownership verification is unavailable")
    if _resource_tenant({"tags": tags}) != request.state.tenant_id:
        raise HTTPException(status_code=404, detail="S3 bucket not found")


@router.post("/ec2/instances/{instance_id}/plans")
def plan_ec2_actions(instance_id: str, request: Request, region: str | None = None):
    if not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", instance_id):
        raise HTTPException(status_code=400, detail="Invalid EC2 instance ID")
    if region is not None and not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-[0-9]", region):
        raise HTTPException(status_code=400, detail="Invalid AWS region")
    _require_tenant_ec2_instance(request, instance_id, region)
    insights = _load_action_insights(
        lambda: aws_service.get_ec2_insights(
            instance_id, **({"region": region} if region else {})
        )
    )

    plans = action_planner.plan_from_ec2_insights(
        instance_id,
        insights,
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

    insights = _load_action_insights(
        lambda: aws_service.get_s3_bucket_insights(
            bucket_name,
            prefix=prefix,
            max_keys=max_keys,
        )
    )

    plans = action_planner.plan_from_s3_insights(
        bucket_name,
        insights,
        prefix=prefix,
    )

    return _plan_response(plans, request)


@router.get("/plans")
def list_plans(
    request: Request,
    status: ActionStatus | None = None,
    risk: RiskLevel | None = None,
    resource_type: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List plans available to this tenant, newest registry entries first."""
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")
    if search is not None and len(search) > 200:
        raise HTTPException(status_code=422, detail="search must be at most 200 characters")
    normalized_search = search.strip().casefold() if search else ""
    with _registry_lock:
        plans = [
            plan for action_id, plan in _plan_registry.items()
            if (not getattr(request.state, "tenant_scoped", False)
                or _plan_tenants.get(action_id) == request.state.tenant_id)
            and (status is None or plan.status == status)
            and (risk is None or plan.risk == risk)
            and (resource_type is None or plan.target.resource_type == resource_type)
            and (not normalized_search or normalized_search in " ".join((
                plan.action_type, plan.target.resource_id, plan.reason,
            )).casefold())
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
def list_pending_approvals(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    risk: RiskLevel | None = None,
    resource_type: str | None = None,
    search: str | None = None,
    sort: str = "oldest",
):
    """List the pending approval queue visible to this tenant."""
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")
    if search is not None and len(search) > 200:
        raise HTTPException(status_code=422, detail="search must be at most 200 characters")
    if sort not in {"oldest", "newest"}:
        raise HTTPException(status_code=422, detail="sort must be oldest or newest")
    normalized_search = search.strip().casefold() if search else ""
    normalized_resource_type = resource_type.strip() if resource_type else None
    if normalized_resource_type is not None and not normalized_resource_type:
        normalized_resource_type = None
    with _registry_lock:
        approvals = [
            plan for action_id, plan in _plan_registry.items()
            if plan.status == ActionStatus.PENDING_APPROVAL
            and (not getattr(request.state, "tenant_scoped", False)
                 or _plan_tenants.get(action_id) == request.state.tenant_id)
            and (risk is None or plan.risk == risk)
            and (normalized_resource_type is None
                 or plan.target.resource_type == normalized_resource_type)
            and (not normalized_search or normalized_search in " ".join((
                action_id, plan.action_type, plan.target.resource_id, plan.reason,
            )).casefold())
        ]
    dated = [plan for plan in approvals if plan.created_at is not None]
    undated = [plan for plan in approvals if plan.created_at is None]
    dated.sort(key=lambda plan: plan.created_at, reverse=(sort == "newest"))
    approvals = dated + undated
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

    old_status = action.status
    old_requires_approval = action.requires_approval
    try:
        evaluated = policy_engine.evaluate(action)
    except (ValueError, TypeError) as exc:
        action.status = old_status
        action.requires_approval = old_requires_approval
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _record_plan_transition(evaluated, request, old_status)
        _persist_plan(evaluated)
    except Exception:
        action.status = old_status
        action.requires_approval = old_requires_approval
        raise
    return _action_response(evaluated)


@router.post("/plans/{action_id}/approve")
def approve_plan(action_id: str, request: Request):
    action = _get_plan(action_id, request)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    old_status = action.status
    old_decision_by, old_decision_reason = action.decision_by, action.decision_reason
    try:
        principal = getattr(request.state, "principal", None)
        approved = approval_manager.approve(
            action, approved_by=getattr(principal, "subject", None)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        _record_plan_transition(approved, request, old_status)
        _persist_plan(approved)
    except Exception:
        action.status, action.decision_by, action.decision_reason = old_status, old_decision_by, old_decision_reason
        raise
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

    old_status = action.status
    old_decision_by, old_decision_reason = action.decision_by, action.decision_reason
    principal = getattr(request.state, "principal", None)
    reviewer = getattr(principal, "subject", None)
    try:
        rejected = approval_manager.reject(action, reviewer, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        _record_plan_transition(rejected, request, old_status)
        _persist_plan(rejected)
    except Exception:
        action.status, action.decision_by, action.decision_reason = old_status, old_decision_by, old_decision_reason
        raise
    return _action_response(rejected)


@router.post("/plans/{action_id}/cancel")
def cancel_plan(action_id: str, request: Request):
    action = _get_plan(action_id, request)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    old_status = action.status
    old_decision_by, old_decision_reason = action.decision_by, action.decision_reason
    try:
        principal = getattr(request.state, "principal", None)
        cancelled = approval_manager.cancel(
            action, cancelled_by=getattr(principal, "subject", None)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        _record_plan_transition(cancelled, request, old_status)
        _persist_plan(cancelled)
    except Exception:
        action.status, action.decision_by, action.decision_reason = old_status, old_decision_by, old_decision_reason
        raise
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

    old_status = action.status
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

    _record_plan_transition(final_action, request, old_status)
    _persist_plan(final_action)

    return {
        "status": "healthy",
        "action": _serialize(final_action),
        "execution": _serialize(execution_result),
    }

