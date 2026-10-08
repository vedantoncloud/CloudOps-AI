from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_success_content_type(monkeypatch):
    class FakeResult:
        count = 0
        active_count = 0
        stale_count = 0
        items = []
        evidence = {
            "store": "sqlite",
            "read_only": True,
            "lease_seconds": 300.0,
            "pending_count": 0,
            "active_count": 0,
            "stale_count": 0,
        }

    class FakeReconciliation:
        def __init__(self, store, *, lease_seconds):
            self.store = store
            self.lease_seconds = lease_seconds

        def inspect(self):
            return FakeResult()

    monkeypatch.setattr(
        reconciliation_api,
        "PersistentAuditReconciliation",
        FakeReconciliation,
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get("/autonomy/audit/reconciliation")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
