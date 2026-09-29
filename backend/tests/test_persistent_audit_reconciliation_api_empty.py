from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_returns_empty_contract_for_empty_store(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"

    PersistentAuditIdempotencyStore(db_path)

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

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["count"] == 0
    assert body["active_count"] == 0
    assert body["stale_count"] == 0
    assert body["items"] == []
    assert body["read_only"] is True

    assert body["evidence"] == {
        "store": "sqlite",
        "read_only": True,
        "lease_seconds": 300.0,
        "pending_count": 0,
        "active_count": 0,
        "stale_count": 0,
    }
