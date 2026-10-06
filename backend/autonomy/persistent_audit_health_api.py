from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from autonomy.persistent_audit_health import PersistentAuditHealthChecker

router = APIRouter(prefix="/autonomy/audit", tags=["audit"])

DEFAULT_DB_PATH = os.getenv(
    "CLOUDOPS_AUDIT_IDEMPOTENCY_DB",
    "cloudops_audit_idempotency.db",
)


class AuditHealthResponse(BaseModel):
    path: str
    total_claims: int = Field(ge=0)
    pending_claims: int = Field(ge=0)
    emitted_claims: int = Field(ge=0)
    evidence_conflicts: int = Field(ge=0)
    evidence: dict[str, object]


class AuditPendingItem(BaseModel):
    run_id: str
    event_type: str
    claimed_at: float
    evidence: dict[str, object]


class AuditPendingResponse(BaseModel):
    count: int = Field(ge=0)
    pending: list[AuditPendingItem]
    read_only: bool

    @model_validator(mode="after")
    def validate_count_matches_pending(self):
        if self.count != len(self.pending):
            raise ValueError("count must match the number of pending items")
        return self


def _checker() -> PersistentAuditHealthChecker:
    return PersistentAuditHealthChecker(Path(DEFAULT_DB_PATH))


@router.get("/health")
def audit_health() -> AuditHealthResponse:
    try:
        health = _checker().inspect()
    except (ValueError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail="Persistent audit idempotency store is not initialized",
        ) from exc

    return {
        "path": health.path,
        "total_claims": health.total_claims,
        "pending_claims": health.pending_claims,
        "emitted_claims": health.emitted_claims,
        "evidence_conflicts": health.evidence_conflicts,
        "evidence": health.evidence,
    }


@router.get("/pending")
def audit_pending_claims() -> AuditPendingResponse:
    try:
        pending = _checker().list_pending()
    except (ValueError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail="Persistent audit idempotency store is not initialized",
        ) from exc

    return {
        "count": len(pending),
        "pending": pending,
        "read_only": True,
    }
