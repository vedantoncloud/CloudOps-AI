from dataclasses import asdict
from enum import Enum

from fastapi import APIRouter, HTTPException

from autonomy.action_planner import ActionPlanner
from services.aws_service import AWSService


router = APIRouter(prefix="/autonomy", tags=["autonomy"])

aws_service = AWSService()
action_planner = ActionPlanner()


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


def _plan_response(plans):
    return {
        "status": "healthy",
        "plan_count": len(plans),
        "plans": [_serialize(plan) for plan in plans],
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
