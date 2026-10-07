from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_preserves_multiple_item_contract(monkeypatch):
    class FakeItem:
        def __init__(
            self,
            run_id,
            event_type,
            status,
            claimed_at,
            age_seconds,
            evidence,
        ):
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
        items = [
            FakeItem(
                "run-active",
                "recovery_completed",
                "active",
                100.0,
                10.0,
                {"source": "active-test"},
            ),
            FakeItem(
                "run-stale",
                "recovery_failed",
                "stale",
                50.0,
                60.0,
                {"source": "stale-test"},
            ),
        ]
        evidence = {
            "store": "sqlite",
            "read_only": True,
            "lease_seconds": 300.0,
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

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get("/autonomy/audit/reconciliation")

    assert response.status_code == 200

    body = response.json()

    assert body["count"] == 2
    assert body["active_count"] == 1
    assert body["stale_count"] == 1
    assert body["read_only"] is True

    assert [item["run_id"] for item in body["items"]] == [
        "run-active",
        "run-stale",
    ]

    assert body["items"][0]["status"] == "active"
    assert body["items"][0]["evidence"] == {"source": "active-test"}

    assert body["items"][1]["status"] == "stale"
    assert body["items"][1]["evidence"] == {"source": "stale-test"}
