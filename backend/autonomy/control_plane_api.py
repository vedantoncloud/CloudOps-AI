from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autonomy.audit_api import audit_trail
from autonomy.gitops import GitOpsChangeStatus
from autonomy.gitops_api import registry as gitops_registry


router = APIRouter(
    prefix="/autonomy/control-plane",
    tags=["control-plane"],
)


class ControlPlaneActionTraceResponse(BaseModel):
    action_id: str
    status: str
    gitops: dict[str, Any] | None
    audit_events: list[dict[str, Any]]

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


@router.get(
    "/actions/{action_id}/trace",
    response_model=ControlPlaneActionTraceResponse,
)
def get_action_trace(action_id: str) -> ControlPlaneActionTraceResponse:
    changes = [
        change_set
        for change_set in gitops_registry.list_all()
        if change_set.source_action_id == action_id
    ]

    audit_events = audit_trail.get_events(action_id)

    if not changes and not audit_events:
        raise HTTPException(
            status_code=404,
            detail=f"Action trace not found: {action_id}",
        )

    latest_change = changes[-1] if changes else None

    gitops = None
    if latest_change is not None:
        gitops = {
            "change_id": latest_change.change_id,
            "source_action_id": latest_change.source_action_id,
            "status": latest_change.status.value,
            "requires_approval": latest_change.requires_approval,
            "approved_by": latest_change.approved_by,
            "change_count": latest_change.change_count,
            "commit_message": latest_change.commit_message,
            "metadata": dict(latest_change.metadata),
            "changes": [
                {
                    "resource_type": change.resource_type,
                    "resource_id": change.resource_id,
                    "field": change.field,
                    "desired_value": change.desired_value,
                    "current_value": change.current_value,
                    "reason": change.reason,
                }
                for change in latest_change.changes
            ],
        }

    status = "unknown"
    if latest_change is not None:
        status = latest_change.status.value
    elif audit_events:
        status = audit_events[-1].new_status

    return ControlPlaneActionTraceResponse(
        action_id=action_id,
        status=status,
        gitops=gitops,
        audit_events=[
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
            for event in audit_events
        ],
    )
