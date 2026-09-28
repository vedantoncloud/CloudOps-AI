from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_classifies_active_and_stale_claims(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_LEASE_SECONDS",
        300.0,
    )

    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    class FakeReconciliation:
        def __init__(self, store, *, lease_seconds):
            self.store = store
            self.lease_seconds = lease_seconds

        def inspect(self):
            from autonomy.persistent_audit_reconciliation import (
                AuditReconciliationItem,
                AuditReconciliationResult,
            )

            return AuditReconciliationResult(
                items=(
                    AuditReconciliationItem(
                        run_id="run-stale",
                        event_type="recovery_completed",
                        status="stale",
                        claimed_at=now.timestamp() - 301,
                        age_seconds=301.0,
                        evidence={"run_id": "run-stale"},
                    ),
                    AuditReconciliationItem(
                        run_id="run-active",
                        event_type="recovery_failed",
                        status="active",
                        claimed_at=now.timestamp() - 10,
                        age_seconds=10.0,
                        evidence={"run_id": "run-active"},
                    ),
                ),
                stale_count=1,
                active_count=1,
                evidence={
                    "store": "sqlite",
                    "read_only": True,
                    "lease_seconds": 300.0,
                    "pending_count": 2,
                    "active_count": 1,
                    "stale_count": 1,
                },
            )

    monkeypatch.setattr(
        reconciliation_api,
        "PersistentAuditReconciliation",
        FakeReconciliation,
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get("/autonomy/audit/reconciliation")

    assert response.status_code == 200

    body = response.json()

    assert body["count"] == 2
    assert body["active_count"] == 1
    assert body["stale_count"] == 1

    assert body["items"][0]["status"] == "stale"
    assert body["items"][1]["status"] == "active"

    assert body["evidence"]["lease_seconds"] == 300.0
    assert body["evidence"]["pending_count"] == 2
    assert body["read_only"] is True
