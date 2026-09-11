from collections import Counter
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from autonomy.audit_api import audit_trail
from autonomy.gitops import GitOpsChangeStatus
from autonomy.gitops_api import registry as gitops_registry


router = APIRouter(
    prefix="/autonomy/control-plane",
    tags=["control-plane"],
)


class ControlPlaneSummaryResponse(BaseModel):
    status: str
    gitops: dict[str, Any]
    audit: dict[str, Any]
    capabilities: dict[str, bool]


def _gitops_summary() -> dict[str, Any]:
    changes = gitops_registry.list_all()

    status_counts = Counter(
        change_set.status.value
        for change_set in changes
    )

    return {
        "total_changes": len(changes),
        "pending_approvals": sum(
            1
            for change_set in changes
            if change_set.status == GitOpsChangeStatus.PENDING_APPROVAL
        ),
        "status_counts": {
            status.value: status_counts.get(status.value, 0)
            for status in GitOpsChangeStatus
        },
        "recent_changes": [
            {
                "change_id": change_set.change_id,
                "source_action_id": change_set.source_action_id,
                "status": change_set.status.value,
                "requires_approval": change_set.requires_approval,
                "change_count": change_set.change_count,
            }
            for change_set in changes[-10:]
        ],
    }


def _audit_summary() -> dict[str, Any]:
    events = audit_trail.get_events()

    return {
        "total_events": len(events),
        "recent_events": [
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
            for event in events[-10:]
        ],
    }


@router.get(
    "/summary",
    response_model=ControlPlaneSummaryResponse,
)
def get_control_plane_summary() -> ControlPlaneSummaryResponse:
    return ControlPlaneSummaryResponse(
        status="operational",
        gitops=_gitops_summary(),
        audit=_audit_summary(),
        capabilities={
            "governed_gitops": True,
            "human_approval": True,
            "audit_trail": True,
            "dry_run_execution": True,
            "real_infrastructure_mutation": False,
        },
    )
