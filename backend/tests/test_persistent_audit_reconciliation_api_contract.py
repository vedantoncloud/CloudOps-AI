from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_preserves_item_order_and_evidence(monkeypatch):
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
        evidence = {
            "store": "sqlite",
            "read_only": True,
            "lease_seconds": 300.0,
            "pending_count": 2,
            "active_count": 1,
            "stale_count": 1,
        }

        items = (
            FakeItem(
                "run-a",
                "recovery_completed",
                "stale",
                100.0,
                301.0,
                {"source": "pending_claim", "run_id": "run-a"},
            ),
            FakeItem(
                "run-b",
                "recovery_failed",
                "active",
                391.0,
                10.0,
                {"source": "pending_claim", "run_id": "run-b"},
            ),
        )

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

    assert [item["run_id"] for item in body["items"]] == ["run-a", "run-b"]
    assert body["items"][0] == {
        "run_id": "run-a",
        "event_type": "recovery_completed",
        "status": "stale",
        "claimed_at": 100.0,
        "age_seconds": 301.0,
        "evidence": {
            "source": "pending_claim",
            "run_id": "run-a",
        },
    }
    assert body["items"][1]["evidence"] == {
        "source": "pending_claim",
        "run_id": "run-b",
    }
