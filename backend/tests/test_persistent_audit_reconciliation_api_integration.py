from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_real_store_integration(monkeypatch, tmp_path):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claim = store.claim(
        run_id="run-integration",
        event_type="recovery_completed",
        evidence={"source": "integration-test", "action_id": "action-1"},
    )
    assert claim.emitted is True

    monkeypatch.setattr(reconciliation_api, "DEFAULT_DB_PATH", str(db_path))
    monkeypatch.setattr(reconciliation_api, "DEFAULT_LEASE_SECONDS", 300.0)

    app = FastAPI()
    app.include_router(reconciliation_api.router)
    client = TestClient(app)

    response = client.get("/autonomy/audit/reconciliation")

    assert response.status_code == 200
    body = response.json()

    assert body["count"] == 1
    assert body["active_count"] == 1
    assert body["stale_count"] == 0
    assert body["read_only"] is True

    assert body["evidence"]["store"] == "sqlite"
    assert body["evidence"]["read_only"] is True
    assert body["evidence"]["lease_seconds"] == 300.0
    assert body["evidence"]["pending_count"] == 1
    assert body["evidence"]["active_count"] == 1
    assert body["evidence"]["stale_count"] == 0

    assert body["items"] == [
        {
            "run_id": "run-integration",
            "event_type": "recovery_completed",
            "status": "active",
            "claimed_at": body["items"][0]["claimed_at"],
            "age_seconds": body["items"][0]["age_seconds"],
            "evidence": {
                "source": "integration-test",
                "action_id": "action-1",
            },
        }
    ]

    assert store.contains("run-integration", "recovery_completed") is True
