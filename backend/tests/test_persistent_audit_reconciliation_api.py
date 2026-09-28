from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.persistent_audit_reconciliation_api import (
    audit_reconciliation,
    router,
)


def _client(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(router)

    db_path = tmp_path / "audit.db"
    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation_api.DEFAULT_DB_PATH",
        str(db_path),
    )
    return TestClient(app), db_path


def test_reconciliation_endpoint_returns_empty_read_only_result(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)

    response = client.get("/autonomy/audit/reconciliation")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["active_count"] == 0
    assert body["stale_count"] == 0
    assert body["items"] == []
    assert body["read_only"] is True
    assert body["evidence"]["read_only"] is True


def test_reconciliation_endpoint_exposes_pending_claim(monkeypatch, tmp_path):
    client, db_path = _client(monkeypatch, tmp_path)

    from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore

    store = PersistentAuditIdempotencyStore(db_path)
    store.claim(
        "run-api",
        "recovery_completed",
        {"run_id": "run-api", "action_id": "action-api"},
    )

    response = client.get("/autonomy/audit/reconciliation")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["active_count"] == 1
    assert body["stale_count"] == 0
    assert body["items"][0]["run_id"] == "run-api"
    assert body["items"][0]["event_type"] == "recovery_completed"
    assert body["items"][0]["status"] == "active"


def test_reconciliation_endpoint_is_read_only(monkeypatch, tmp_path):
    client, db_path = _client(monkeypatch, tmp_path)

    from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore

    store = PersistentAuditIdempotencyStore(db_path)
    store.claim(
        "run-readonly",
        "recovery_failed",
        {"run_id": "run-readonly"},
    )

    before = store.contains("run-readonly", "recovery_failed")

    response = client.get("/autonomy/audit/reconciliation")

    after = store.contains("run-readonly", "recovery_failed")

    assert response.status_code == 200
    assert before is True
    assert after is True
    assert response.json()["read_only"] is True


def test_reconciliation_endpoint_maps_invalid_store_to_503(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation_api.DEFAULT_DB_PATH",
        str(tmp_path / "missing-parent" / "audit.db"),
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/autonomy/audit/reconciliation")

    assert response.status_code == 503


def test_reconciliation_function_contract():
    assert callable(audit_reconciliation)
    assert isinstance(router.prefix, str)
    assert router.prefix == "/autonomy/audit"
