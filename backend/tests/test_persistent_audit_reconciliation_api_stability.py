from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def _app():
    app = FastAPI()
    app.include_router(reconciliation_api.router)
    return app


def test_reconciliation_api_returns_stable_item_order(monkeypatch):
    class FakeItem:
        def __init__(self, run_id, event_type, status, claimed_at, age_seconds, evidence):
            self.run_id = run_id
            self.event_type = event_type
            self.status = status
            self.claimed_at = claimed_at
            self.age_seconds = age_seconds
            self.evidence = evidence

    class FakeResult:
        count = 2
        active_count = 1
        stale_count = 1
        items = (
            FakeItem("run-a", "event-a", "active", 100.0, 10.0, {"x": 1}),
            FakeItem("run-b", "event-b", "stale", 50.0, 60.0, {"x": 2}),
        )
        evidence = {
            "store": "sqlite",
            "read_only": True,
            "lease_seconds": 50.0,
            "pending_count": 2,
            "active_count": 1,
            "stale_count": 1,
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

    client = TestClient(_app())

    first = client.get("/autonomy/audit/reconciliation")
    second = client.get("/autonomy/audit/reconciliation")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    assert [item["run_id"] for item in first.json()["items"]] == [
        "run-a",
        "run-b",
    ]
