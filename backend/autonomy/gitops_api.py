from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from autonomy.audit_api import audit_trail
from autonomy.gitops import GitOpsChangeStatus, GitOpsEngine
from autonomy.gitops_registry import GitOpsChangeSetRegistry


router = APIRouter(
    prefix="/autonomy/gitops",
    tags=["autonomy-gitops"],
)

registry = GitOpsChangeSetRegistry(audit_trail=audit_trail)
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


@router.get(
    "/changes",
    response_model=list[GitOpsChangeResponse],
)
def list_gitops_changes(request: Request) -> list[GitOpsChangeResponse]:
    return [
        _serialize_change_set(change_set)
        for change_set in registry.list_all()
        if not getattr(request.state, "tenant_scoped", False)
        or change_set.metadata.get("tenant_id") == request.state.tenant_id
    ]


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
