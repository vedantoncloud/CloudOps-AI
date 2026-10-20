import csv
import io
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from autonomy.audit_api import audit_trail
from autonomy.gitops import GitOpsChangeStatus, GitOpsEngine
from autonomy.gitops_registry import GitOpsChangeSetRegistry


router = APIRouter(
    prefix="/autonomy/gitops",
    tags=["autonomy-gitops"],
)

registry = GitOpsChangeSetRegistry(
    audit_trail=audit_trail,
    database_path=os.getenv("CLOUDOPS_GITOPS_DB_PATH")
    or Path(__file__).resolve().parents[1] / "gitops_changes.db",
)
engine = GitOpsEngine()


class GitOpsChangeResponse(BaseModel):
    change_id: str
    source_action_id: str
    status: str
    requires_approval: bool
    approved_by: str | None
    change_count: int
    commit_message: str
    changes: list[dict[str, Any]]
    metadata: dict[str, Any]


class GitOpsChangePageResponse(BaseModel):
    changes: list[GitOpsChangeResponse]
    total: int
    limit: int
    offset: int


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=1)


class RejectionRequest(BaseModel):
    rejected_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ApplyRequest(BaseModel):
    dry_run: bool = True


class VerifyRequest(BaseModel):
    observed_values: dict[str, Any] | None = None


class ApplyResponse(BaseModel):
    change_id: str
    success: bool
    dry_run: bool
    status: str
    applied_changes: int
    message: str


class VerifyResponse(BaseModel):
    change_id: str
    verified: bool
    status: str


def _serialize_change_set(change_set) -> GitOpsChangeResponse:
    manifest = change_set.to_manifest()

    return GitOpsChangeResponse(
        change_id=change_set.change_id,
        source_action_id=change_set.source_action_id,
        status=change_set.status.value,
        requires_approval=change_set.requires_approval,
        approved_by=change_set.approved_by,
        change_count=change_set.change_count,
        commit_message=change_set.commit_message,
        changes=manifest["changes"],
        metadata=dict(change_set.metadata),
    )


def _visible_change(change_set, request: Request):
    """Apply fail-closed tenant visibility to change sets in token mode."""
    if (
        getattr(request.state, "tenant_scoped", False)
        and change_set.metadata.get("tenant_id") != request.state.tenant_id
    ):
        raise HTTPException(status_code=404, detail="GitOps change set not found")
    return change_set


def _change_actor(request: Request, claimed_actor: str) -> str:
    principal = getattr(request.state, "principal", None)
    return principal.subject if principal is not None else claimed_actor


def _authenticated_actor(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    return principal.subject if principal is not None else None


def _matching_changes(request: Request, status: str | None, search: str | None):
    valid_statuses = {item.value for item in GitOpsChangeStatus}
    if status is not None and status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid GitOps change status")
    normalized_search = search.strip().casefold() if search else ""
    return [
        change_set
        for change_set in reversed(registry.list_all())
        if (
            not getattr(request.state, "tenant_scoped", False)
            or change_set.metadata.get("tenant_id") == request.state.tenant_id
        )
        and (status is None or change_set.status.value == status)
        and (
            not normalized_search
            or normalized_search in " ".join((
                change_set.change_id,
                change_set.source_action_id,
                change_set.commit_message,
                *(f"{change.resource_type} {change.resource_id} {change.field} {change.reason}"
                  for change in change_set.changes),
            )).casefold()
        )
    ]


def _spreadsheet_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@router.get(
    "/changes",
    response_model=GitOpsChangePageResponse,
)
def list_gitops_changes(
    request: Request,
    status: str | None = None,
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> GitOpsChangePageResponse:
    visible = _matching_changes(request, status, search)
    return GitOpsChangePageResponse(
        changes=[_serialize_change_set(item) for item in visible[offset:offset + limit]],
        total=len(visible),
        limit=limit,
        offset=offset,
    )


@router.get("/changes/export.csv", response_class=Response)
def export_gitops_changes(
    request: Request,
    status: str | None = None,
    search: str | None = Query(default=None, max_length=200),
) -> Response:
    """Export all matching, tenant-visible proposals as spreadsheet-safe CSV."""
    visible = _matching_changes(request, status, search)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(("Change ID", "Source action ID", "Status", "Requires approval",
                     "Approved by", "Commit message", "Resource type", "Resource ID",
                     "Field", "Current value", "Desired value", "Reason"))
    for change_set in visible:
        for change in change_set.changes:
            writer.writerow(tuple(_spreadsheet_cell(value) for value in (
                change_set.change_id, change_set.source_action_id,
                change_set.status.value, change_set.requires_approval,
                change_set.approved_by, change_set.commit_message,
                change.resource_type, change.resource_id, change.field,
                change.current_value, change.desired_value, change.reason,
            )))
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="gitops-changes.csv"'},
    )


@router.get(
    "/changes/pending",
    response_model=list[GitOpsChangeResponse],
)
def list_pending_gitops_changes(request: Request) -> list[GitOpsChangeResponse]:
    return [
        _serialize_change_set(change_set)
        for change_set in registry.list_pending()
        if not getattr(request.state, "tenant_scoped", False)
        or change_set.metadata.get("tenant_id") == request.state.tenant_id
    ]


@router.get(
    "/changes/{change_id}",
    response_model=GitOpsChangeResponse,
)
def get_gitops_change(change_id: str, request: Request) -> GitOpsChangeResponse:
    change_set = registry.get(change_id)

    if change_set is None:
        raise HTTPException(
            status_code=404,
            detail=f"GitOps change set not found: {change_id}",
        )

    return _serialize_change_set(_visible_change(change_set, request))


@router.post(
    "/changes/{change_id}/approve",
    response_model=GitOpsChangeResponse,
)
def approve_gitops_change(
    change_id: str,
    request: ApprovalRequest,
    http_request: Request,
) -> GitOpsChangeResponse:
    try:
        _visible_change(registry.require(change_id), http_request)
        change_set = registry.approve(
            change_id,
            _change_actor(http_request, request.approved_by),
            engine=engine,
            actor_id=_change_actor(http_request, request.approved_by),
        )
        return _serialize_change_set(_visible_change(change_set, http_request))

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@router.post(
    "/changes/{change_id}/reject",
    response_model=GitOpsChangeResponse,
)
def reject_gitops_change(
    change_id: str,
    request: RejectionRequest,
    http_request: Request,
) -> GitOpsChangeResponse:
    try:
        _visible_change(registry.require(change_id), http_request)
        change_set = registry.reject(
            change_id,
            _change_actor(http_request, request.rejected_by),
            request.reason,
            engine=engine,
            actor_id=_change_actor(http_request, request.rejected_by),
        )
        return _serialize_change_set(_visible_change(change_set, http_request))

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@router.post(
    "/changes/{change_id}/apply",
    response_model=ApplyResponse,
)
def apply_gitops_change(
    change_id: str,
    request: ApplyRequest,
    http_request: Request,
) -> ApplyResponse:
    try:
        _visible_change(registry.require(change_id), http_request)
        result = registry.apply(
            change_id,
            dry_run=request.dry_run,
            engine=engine,
            actor_id=_authenticated_actor(http_request),
        )

        return ApplyResponse(
            change_id=result.change_id,
            success=result.success,
            dry_run=result.dry_run,
            status=result.status.value,
            applied_changes=result.applied_changes,
            message=result.message,
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@router.post(
    "/changes/{change_id}/verify",
    response_model=VerifyResponse,
)
def verify_gitops_change(
    change_id: str,
    request: VerifyRequest,
    http_request: Request,
) -> VerifyResponse:
    try:
        _visible_change(registry.require(change_id), http_request)
        verified = registry.verify(
            change_id,
            observed_values=request.observed_values,
            engine=engine,
            actor_id=_authenticated_actor(http_request),
        )

        change_set = registry.require(change_id)

        return VerifyResponse(
            change_id=change_id,
            verified=verified,
            status=change_set.status.value,
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
