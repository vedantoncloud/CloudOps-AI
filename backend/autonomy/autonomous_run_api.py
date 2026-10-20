from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.audit_api import audit_trail
from autonomy.autonomous_lifecycle import AutonomousLifecycleOrchestrator
from autonomy.governed_autonomous_run import GovernedAutonomousRun, GovernedAutonomousRunResult


router = APIRouter(
    prefix="/autonomy",
    tags=["autonomous-run"],
)

def _create_runner() -> GovernedAutonomousRun:
    return GovernedAutonomousRun(
        lifecycle=AutonomousLifecycleOrchestrator(audit_trail=audit_trail)
    )


runner = _create_runner()


@router.get("/runs")
def list_autonomous_runs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    outcome: str | None = Query(default=None, pattern="^(completed|awaiting_approval|blocked|in_progress)$"),
    search: str | None = Query(default=None, max_length=200),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    """Return the authenticated principal's durable autonomous run history."""
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")

    def as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    start = as_utc(start_time) if start_time else None
    end = as_utc(end_time) if end_time else None
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start_time must be at or before end_time")

    principal = getattr(request.state, "principal", None)
    actor_id = getattr(principal, "subject", None)
    if not actor_id:
        raise HTTPException(status_code=401, detail="Authenticated principal required")

    grouped: dict[str, list[Any]] = {}
    for event in audit_trail.get_events():
        if event.actor_id != actor_id or not event.event.startswith("autonomous_"):
            continue
        grouped.setdefault(event.action_id, []).append(event)

    runs = []
    for action_id, events in grouped.items():
        first, latest = events[0], events[-1]
        run_outcome = {
            "autonomous_lifecycle_completed": "completed",
            "autonomous_lifecycle_waiting": "awaiting_approval",
            "autonomous_lifecycle_blocked": "blocked",
        }.get(latest.event, "in_progress")
        runs.append({
            "action_id": action_id,
            "action_type": first.action_type,
            "resource_type": first.resource_type,
            "resource_id": first.resource_id,
            "status": latest.new_status,
            "outcome": run_outcome,
            "started_at": first.timestamp,
            "updated_at": latest.timestamp,
            "actor_id": actor_id,
            "dry_run": first.details.get("dry_run"),
        })

    runs.sort(key=lambda run: (run["updated_at"], run["action_id"]), reverse=True)
    if start or end:
        def in_window(run: dict[str, Any]) -> bool:
            try:
                updated = as_utc(datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00")))
            except (TypeError, ValueError):
                return False
            return (start is None or updated >= start) and (end is None or updated <= end)

        runs = [run for run in runs if in_window(run)]
    if outcome:
        runs = [run for run in runs if run["outcome"] == outcome]
    if search:
        needle = search.strip().casefold()
        if needle:
            runs = [
                run for run in runs
                if any(needle in str(run[field]).casefold() for field in (
                    "action_id", "action_type", "resource_type", "resource_id", "outcome", "status"
                ))
            ]
    total = len(runs)
    return {"runs": runs[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{action_id}")
def get_autonomous_run(action_id: str, request: Request) -> dict[str, Any]:
    """Return lifecycle events for one run owned by the authenticated actor."""
    principal = getattr(request.state, "principal", None)
    actor_id = getattr(principal, "subject", None)
    if not actor_id:
        raise HTTPException(status_code=401, detail="Authenticated principal required")

    events = [
        event for event in audit_trail.get_events(action_id=action_id)
        if event.actor_id == actor_id and event.event.startswith("autonomous_")
    ]
    if not events:
        raise HTTPException(status_code=404, detail="Autonomous run not found")

    return {
        "action_id": action_id,
        "actor_id": actor_id,
        "events": [
            {
                "event": event.event,
                "timestamp": event.timestamp,
                "old_status": event.old_status,
                "new_status": event.new_status,
                "action_type": event.action_type,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "details": event.details,
            }
            for event in events
        ],
    }


class AutonomousRunRequest(BaseModel):
    provider: str = Field(default="aws", min_length=1)
    action_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = True
    rollback_available: bool = True
    approved_by: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    idempotency_key: str | None = None
    idempotency_seen: bool = False
    dry_run: bool = True


def _action(payload: AutonomousRunRequest) -> ActionPlan:
    return ActionPlan(
        action_type=payload.action_type.strip(),
        target=ActionTarget(
            resource_type=payload.resource_type.strip(),
            resource_id=payload.resource_id.strip(),
        ),
        reason=payload.reason.strip(),
        risk=payload.risk,
        requires_approval=payload.requires_approval,
        rollback_available=payload.rollback_available,
        status=ActionStatus.PENDING_APPROVAL,
        action_id=payload.action_id.strip(),
    )


def _result(result: GovernedAutonomousRunResult) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "outcome": result.outcome,
            "execution_started": result.execution_started,
            "blocked": result.blocked,
            "requires_human_review": result.requires_human_review,
            "completed": result.completed,
            "governance": result.governance,
            "lifecycle": result.lifecycle,
            "evidence": dict(result.evidence),
        }
    )


@router.post("/run")
def run_autonomous(payload: AutonomousRunRequest, request: Request) -> dict[str, Any]:
    try:
        principal = getattr(request.state, "principal", None)
        actor_id = getattr(principal, "subject", None)
        # Reviewer fields select a requested transition, but identity comes from
        # the authenticated principal. Never accept a caller-supplied actor.
        approved_by = actor_id if payload.approved_by is not None and actor_id else payload.approved_by
        rejected_by = actor_id if payload.rejected_by is not None and actor_id else payload.rejected_by
        if rejected_by is not None and not (payload.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when rejecting.")
        action = _action(payload)
        result = runner.run(
            provider=payload.provider.strip(),
            action=action,
            resource_type=payload.resource_type.strip(),
            resource_id=payload.resource_id.strip(),
            approved_by=approved_by,
            rejected_by=rejected_by,
            rejection_reason=payload.rejection_reason,
            idempotency_key=payload.idempotency_key,
            idempotency_seen=payload.idempotency_seen,
            dry_run=payload.dry_run,
            actor_id=actor_id,
        )
        return _result(result)
    except (ValueError, PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
