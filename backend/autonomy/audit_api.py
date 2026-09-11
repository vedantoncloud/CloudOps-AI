from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from autonomy.audit import AuditEvent, AuditTrail


router = APIRouter(
    prefix="/autonomy/audit",
    tags=["autonomy-audit"],
)

audit_trail = AuditTrail()


class AuditEventResponse(BaseModel):
    action_id: str
    action_type: str
    resource_type: str
    resource_id: str
    old_status: str
    new_status: str
    event: str
    timestamp: str
    details: dict[str, Any]


def _serialize(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        action_id=event.action_id,
        action_type=event.action_type,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        old_status=event.old_status,
        new_status=event.new_status,
        event=event.event,
        timestamp=event.timestamp,
        details=dict(event.details),
    )


@router.get(
    "/events",
    response_model=list[AuditEventResponse],
)
def list_audit_events(
    action_id: str | None = Query(default=None),
) -> list[AuditEventResponse]:
    return [
        _serialize(event)
        for event in audit_trail.get_events(action_id=action_id)
    ]
