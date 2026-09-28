from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation_api import router


def test_reconciliation_api_exposes_deterministic_evidence_contract(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation_api.DEFAULT_DB_PATH",
        str(db_path),
    )

    store = PersistentAuditIdempotencyStore(db_path)
    store.claim(
        "evidence-run",
        "recovery_completed",
        {"run_id": "evidence-run"},
    )

    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/autonomy/audit/reconciliation")

    assert response.status_code == 200

    body = response.json()
    evidence = body["evidence"]

    assert evidence["store"] == "sqlite"
    assert evidence["read_only"] is True
    assert evidence["lease_seconds"] == 300.0
    assert evidence["pending_count"] == 1
    assert evidence["active_count"] == 1
    assert evidence["stale_count"] == 0
