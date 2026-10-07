from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_preserves_nested_item_evidence(monkeypatch):
    class FakeItem:
        run_id = "run-evidence"
        event_type = "recovery_completed"
        status = "active"
        claimed_at = 123.0
        age_seconds = 5.0
        evidence = {
            "source": "audit-store",
            "claim": {
                "owner": "worker-1",
                "attempt": 2,
            },
            "signals": ["lease", "pending"],
        }

    class FakeResult:
        count = 1
        active_count = 1
        stale_count = 0
        items = [FakeItem()]
        evidence = {
            "store": "sqlite",
            "read_only": True,
            "lease_seconds": 300.0,
            "pending_count": 1,
            "active_count": 1,
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

    body = response.json()

    assert body["items"][0]["evidence"] == {
        "source": "audit-store",
        "claim": {
            "owner": "worker-1",
            "attempt": 2,
        },
        "signals": ["lease", "pending"],
    }
