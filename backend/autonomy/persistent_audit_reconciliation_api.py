from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


router = APIRouter(prefix="/autonomy/audit", tags=["audit"])

DEFAULT_DB_PATH = os.getenv(
    "CLOUDOPS_AUDIT_IDEMPOTENCY_DB",
    "cloudops_audit_idempotency.db",
)
DEFAULT_LEASE_SECONDS = 300.0


def _store() -> PersistentAuditIdempotencyStore:
    return PersistentAuditIdempotencyStore(Path(DEFAULT_DB_PATH))


def _reconciliation() -> PersistentAuditReconciliation:
    return PersistentAuditReconciliation(
        _store(),
        lease_seconds=DEFAULT_LEASE_SECONDS,
    )


@router.get("/reconciliation")
def audit_reconciliation():
    try:
        result = _reconciliation().inspect()
    except (ValueError, OSError, sqlite3.OperationalError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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