from dataclasses import asdict
from enum import Enum
from threading import Lock

from fastapi import APIRouter, HTTPException

from autonomy.action_planner import ActionPlanner
from autonomy.approval import ApprovalManager
from autonomy.policy_engine import PolicyEngine
from services.aws_service import AWSService


router = APIRouter(prefix="/autonomy", tags=["autonomy"])

aws_service = AWSService()
action_planner = ActionPlanner()
policy_engine = PolicyEngine()
approval_manager = ApprovalManager()

_plan_registry = {}
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
        return {
            key: _serialize(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_serialize(item) for item in value]

    return value


def _store_plans(plans):
    with _registry_lock:
        for plan in plans:
            _plan_registry[plan.action_id] = plan


def _get_plan(action_id: str):
    with _registry_lock:
        return _plan_registry.get(action_id)


def _plan_response(plans):
    _store_plans(plans)
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


@router.get("/ec2/instances/{instance_id}/plans")
def plan_ec2_actions(instance_id: str):
    result = aws_service.get_ec2_insights(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(status_code=403, detail=result["error"])

    plans = action_planner.plan_from_ec2_insights(
        instance_id,
        result.get("insights", []),
    )

    return _plan_response(plans)


@router.get("/s3/buckets/{bucket_name}/plans")
def plan_s3_actions(
    bucket_name: str,
    prefix: str | None = None,
    max_keys: int | None = None,
):
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

    return _plan_response(plans)


@router.post("/plans/{action_id}/evaluate")
def evaluate_plan(action_id: str):
    action = _get_plan(action_id)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    try:
        evaluated = policy_engine.evaluate(action)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _action_response(evaluated)


@router.post("/plans/{action_id}/approve")
def approve_plan(action_id: str):
    action = _get_plan(action_id)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    try:
        approved = approval_manager.approve(action)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _action_response(approved)


@router.post("/plans/{action_id}/cancel")
def cancel_plan(action_id: str):
    action = _get_plan(action_id)

    if action is None:
        raise HTTPException(status_code=404, detail="Action plan not found")

    try:
        cancelled = approval_manager.cancel(action)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _action_response(cancelled)
