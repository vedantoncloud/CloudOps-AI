import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from autonomy.audit import AuditEvent
from autonomy.persistent_audit_trail import PersistentAuditTrail
from auth import require_role


router = APIRouter(
    prefix="/autonomy/audit",
    tags=["autonomy-audit"],
)

audit_trail = PersistentAuditTrail(
    os.environ.get("CLOUDOPS_AUDIT_EVENTS_DB", "cloudops_audit_events.db")
)


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


@router.get("/chain/export")
def export_verifiable_audit_chain(request: Request) -> dict[str, Any]:
    """Export the complete audit chain with hashes for offline verification."""
    require_role(request.state.principal, "admin")
    try:
        return audit_trail.get_verifiable_export()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Audit chain integrity check failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Audit chain export unavailable") from exc


def _download_sqlite_backup(request: Request, store_name: str, source_database: str | Path) -> StreamingResponse:
    """Download a consistent online SQLite snapshot for offline recovery."""
    require_role(request.state.principal, "admin")
    snapshot_path: str | None = None
    try:
        source_path = Path(source_database).resolve(strict=True)
        descriptor, snapshot_path = tempfile.mkstemp(prefix=f"cloudops-{store_name}-", suffix=".db")
        os.close(descriptor)
        with sqlite3.connect(
            f"{source_path.as_uri()}?mode=ro", uri=True, timeout=5
        ) as source, sqlite3.connect(snapshot_path, timeout=5) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise sqlite3.DatabaseError("snapshot integrity check failed")
        filename = f"cloudops-{store_name}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.db"

        def stream_snapshot():
            try:
                with open(snapshot_path, "rb") as snapshot:
                    while chunk := snapshot.read(64 * 1024):
                        yield chunk
            finally:
                try:
                    os.unlink(snapshot_path)
                except OSError:
                    pass

        return StreamingResponse(
            stream_snapshot(),
            media_type="application/vnd.sqlite3",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        if snapshot_path:
            try:
                os.unlink(snapshot_path)
            except OSError:
                pass
        display_name = {"audit": "Audit", "action-plans": "Action plan", "gitops": "GitOps"}[store_name]
        raise HTTPException(status_code=503, detail=f"{display_name} database backup unavailable") from exc


@router.get("/database/backup", response_class=StreamingResponse)
def download_audit_database_backup(request: Request) -> StreamingResponse:
    return _download_sqlite_backup(request, "audit", audit_trail.database_path)


@router.get("/database/backup/{store_name}", response_class=StreamingResponse)
def download_operational_database_backup(store_name: str, request: Request) -> StreamingResponse:
    """Back up one explicitly supported operational SQLite store."""
    require_role(request.state.principal, "admin")
    if store_name == "action-plans":
        from autonomy.api import action_plan_store

        source = action_plan_store.database_path
    elif store_name == "gitops":
        from autonomy.gitops_api import registry

        source = registry.database_path
        if source is None:
            raise HTTPException(status_code=503, detail="GitOps database backup unavailable")
    else:
        raise HTTPException(status_code=404, detail="Unknown database backup store")
    return _download_sqlite_backup(request, store_name, source)


def _filter_audit_events(
    *,
    action_id: str | None = None,
    resource_id: str | None = None,
    resource_type: str | None = None,
    event: str | None = None,
    action_type: str | None = None,
    new_status: str | None = None,
    actor_id: str | None = None,
    tenant_id: str | None = None,
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

    if new_status is not None:
        events = [item for item in events if item.new_status == new_status]

    if actor_id is not None:
        events = [item for item in events if item.actor_id == actor_id]

    if tenant_id is not None:
        # Legacy and unattributed events intentionally fail closed in tenant
        # mode; actor identity alone is not a tenant boundary.
        events = [item for item in events if item.details.get("tenant_id") == tenant_id]

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
    request: Request,
    action_id: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    event: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    new_status: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEventResponse]:
    actor_id = _visible_actor_filter(request, actor_id)
    tenant_id = _visible_tenant_filter(request)
    events = _filter_audit_events(
        action_id=action_id,
        resource_id=resource_id,
        resource_type=resource_type,
        event=event,
        action_type=action_type,
        new_status=new_status,
        actor_id=actor_id,
        tenant_id=tenant_id,
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
    request: Request,
    action_id: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    event: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    new_status: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> Response:
    """Export matching audit events as newline-delimited JSON."""
    actor_id = _visible_actor_filter(request, actor_id)
    tenant_id = _visible_tenant_filter(request)
    events = _filter_audit_events(
        action_id=action_id,
        resource_id=resource_id,
        resource_type=resource_type,
        event=event,
        action_type=action_type,
        new_status=new_status,
        actor_id=actor_id,
        tenant_id=tenant_id,
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


def _visible_actor_filter(request: Request, requested_actor: str | None) -> str | None:
    """Restrict non-admin audit feeds and exports to their own events."""
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.role == "admin":
        return requested_actor
    if requested_actor is not None and requested_actor != principal.subject:
        raise HTTPException(status_code=403, detail="Audit events are limited to the authenticated actor")
    return principal.subject


def _visible_tenant_filter(request: Request) -> str | None:
    """Scope tenant users to attributed events; admins keep shared visibility."""
    principal = getattr(request.state, "principal", None)
    if (
        principal is None
        or principal.role == "admin"
        or not getattr(request.state, "tenant_scoped", False)
    ):
        return None
    return getattr(request.state, "tenant_id", None)
