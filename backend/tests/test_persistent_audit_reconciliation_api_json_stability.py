from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_response_is_json_serialization_stable(monkeypatch):
    class FakeItem:
        run_id = "run-json-stable"
        event_type = "recovery_completed"
        status = "active"
        claimed_at = 123.5
        age_seconds = 4.25
        evidence = {
            "source": "audit-store",
            "attempt": 1,
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
    serialized = json.dumps(body, sort_keys=True)
    round_tripped = json.loads(serialized)

    assert round_tripped == body
    assert round_tripped["read_only"] is True
    assert round_tripped["items"][0]["status"] == "active"
    assert round_tripped["items"][0]["claimed_at"] == 123.5
    assert round_tripped["items"][0]["age_seconds"] == 4.25
