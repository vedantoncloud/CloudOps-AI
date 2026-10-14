import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from autonomy.audit import AuditEvent, AuditTrail


router = APIRouter(
    prefix="/autonomy/audit",
    tags=["autonomy-audit"],
)

audit_trail = AuditTrail()


class AuditIntegrityResponse(BaseModel):
    valid: bool
    event_count: int
    first_invalid_index: int | None


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
    actor_id: str | None = None


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
        actor_id=event.actor_id,
    )


@router.get(
    "/integrity",
    response_model=AuditIntegrityResponse,
)
def verify_audit_integrity() -> AuditIntegrityResponse:
    result = audit_trail.get_integrity_diagnostics()
    return AuditIntegrityResponse(
        valid=result.valid,
        event_count=result.event_count,
        first_invalid_index=result.first_invalid_index,
    )


def _filter_audit_events(
    *,
    action_id: str | None = None,
    resource_id: str | None = None,
    resource_type: str | None = None,
    event: str | None = None,
    action_type: str | None = None,
    actor_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[AuditEvent]:
    """Apply shared filters; naive datetimes are interpreted as UTC."""
    start = _normalize_datetime(start_time) if start_time is not None else None
    end = _normalize_datetime(end_time) if end_time is not None else None
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start_time must be at or before end_time")

    events = audit_trail.get_events(action_id=action_id)

    if resource_id is not None:
        events = [item for item in events if item.resource_id == resource_id]

    if resource_type is not None:
        events = [item for item in events if item.resource_type == resource_type]

    if event is not None:
        events = [item for item in events if item.event == event]

    if action_type is not None:
        events = [item for item in events if item.action_type == action_type]

    if actor_id is not None:
        events = [item for item in events if item.actor_id == actor_id]

    if start is not None or end is not None:
        def within_range(item: AuditEvent) -> bool:
            try:
                timestamp = _normalize_datetime(datetime.fromisoformat(item.timestamp))
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=500,
                    detail="Audit event contains an invalid timestamp",
                ) from exc
            return (start is None or timestamp >= start) and (end is None or timestamp <= end)

        events = [item for item in events if within_range(item)]

    return events


def _normalize_datetime(value: datetime) -> datetime:
    """Normalize aware times to UTC and treat naive times as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get(
    "/events",
    response_model=list[AuditEventResponse],
)
def list_audit_events(
    action_id: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    event: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEventResponse]:
    events = _filter_audit_events(
        action_id=action_id,
        resource_id=resource_id,
        resource_type=resource_type,
        event=event,
        action_type=action_type,
        actor_id=actor_id,
        start_time=start_time,
        end_time=end_time,
    )

    events = events[offset:]
    if limit is not None:
        events = events[:limit]

    return [_serialize(item) for item in events]


@router.get(
    "/events/export",
    response_class=Response,
)
def export_audit_events(
    action_id: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    event: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> Response:
    """Export matching audit events as newline-delimited JSON."""
    events = _filter_audit_events(
        action_id=action_id,
        resource_id=resource_id,
        resource_type=resource_type,
        event=event,
        action_type=action_type,
        actor_id=actor_id,
        start_time=start_time,
        end_time=end_time,
    )

    events = events[offset:]
    if limit is not None:
        events = events[:limit]

    lines = [
        json.dumps(_serialize(item).dict(), sort_keys=True)
        for item in events
    ]

    return Response(
        content="\n".join(lines),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="audit-events.jsonl"'
        },
    )
