from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


router = APIRouter(prefix="/autonomy/audit", tags=["audit"])

DEFAULT_DB_PATH = os.getenv(
    "CLOUDOPS_AUDIT_IDEMPOTENCY_DB",
    "cloudops_audit_idempotency.db",
)
DEFAULT_LEASE_SECONDS = 300.0


class AuditReconciliationEvidence(BaseModel):
    store: str = ""
    read_only: bool = False
    lease_seconds: float = Field(ge=0)
    pending_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def validate_counts(self):
        if self.pending_count != self.active_count + self.stale_count:
            raise ValueError(
                "pending_count must equal active_count plus stale_count"
            )
        return self


class AuditReconciliationItemResponse(BaseModel):
    run_id: str
    event_type: str
    status: Literal["active", "stale"]
    claimed_at: float = Field(ge=0)
    age_seconds: float = Field(ge=0)
    evidence: dict[str, object]


class AuditReconciliationErrorResponse(BaseModel):
    detail: str


class AuditReconciliationResponse(BaseModel):
    count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)
    items: list[AuditReconciliationItemResponse]
    evidence: AuditReconciliationEvidence
    read_only: Literal[True]

    @model_validator(mode="after")
    def validate_counts(self):
        if self.count != len(self.items):
            raise ValueError("count must match the number of items")
        if self.count != self.active_count + self.stale_count:
            raise ValueError(
                "count must equal active_count plus stale_count"
            )
        return self


def _store() -> PersistentAuditIdempotencyStore:
    return PersistentAuditIdempotencyStore(Path(DEFAULT_DB_PATH))


def _reconciliation() -> PersistentAuditReconciliation:
    return PersistentAuditReconciliation(
        _store(),
        lease_seconds=DEFAULT_LEASE_SECONDS,
    )


@router.get(
    "/reconciliation",
    responses={
        503: {
            "model": AuditReconciliationErrorResponse,
            "description": "Persistent audit reconciliation is unavailable",
        }
    },
)
def audit_reconciliation() -> AuditReconciliationResponse:
    try:
        result = _reconciliation().inspect()
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail="Persistent audit reconciliation is unavailable",
        ) from exc

    return {
        "count": result.count,
        "active_count": result.active_count,
        "stale_count": result.stale_count,
        "items": [
            {
                "run_id": item.run_id,
                "event_type": item.event_type,
                "status": item.status,
                "claimed_at": item.claimed_at,
                "age_seconds": item.age_seconds,
                "evidence": item.evidence,
            }
            for item in result.items
        ],
        "evidence": result.evidence,
        "read_only": True,
    }
