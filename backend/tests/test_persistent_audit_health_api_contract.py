from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_health_api import router
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def build_client(monkeypatch, path: Path) -> TestClient:
    monkeypatch.setattr(
        "autonomy.persistent_audit_health_api.DEFAULT_DB_PATH",
        str(path),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_health_api_contract_reports_consistent_counts(tmp_path, monkeypatch):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    pending = store.claim(
        "contract-pending",
        "recovery_failed",
        {"action_id": "pending"},
    )
    emitted = store.claim(
        "contract-emitted",
        "recovery_completed",
        {"action_id": "emitted"},
    )

    assert store.mark_emitted(
        "contract-emitted",
        "recovery_completed",
        emitted.claim_token,
    )

    response = build_client(monkeypatch, path).get(
        "/autonomy/audit/health"
    )

    assert response.status_code == 200
    body = response.json()

    assert body["total_claims"] == 2
    assert body["pending_claims"] == 1
    assert body["emitted_claims"] == 1
    assert body["evidence_conflicts"] == 0
    assert body["evidence"]["store"] == "sqlite"
    assert body["evidence"]["read_only"] is True
    assert body["evidence"]["consistent"] is True
    assert pending.claim_token


def test_pending_api_is_deterministic_and_does_not_mutate_store(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("contract-b", "recovery_failed", {"action_id": "b"})
    store.claim("contract-a", "recovery_failed", {"action_id": "a"})

    before = PersistentAuditHealthChecker(path).inspect()
    client = build_client(monkeypatch, path)

    first = client.get("/autonomy/audit/pending")
    second = client.get("/autonomy/audit/pending")
    after = PersistentAuditHealthChecker(path).inspect()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["count"] == 2
    assert first.json()["read_only"] is True
    assert [
        item["run_id"] for item in first.json()["pending"]
    ] == ["contract-a", "contract-b"]
    assert before == after


def test_health_and_pending_api_report_malformed_database(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "malformed.db"

    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE unrelated_data (value TEXT)"
        )

    client = build_client(monkeypatch, path)

    health = client.get("/autonomy/audit/health")
    pending = client.get("/autonomy/audit/pending")

    assert health.status_code == 503
    assert pending.status_code == 503
    assert "not initialized" in health.json()["detail"]
    assert "not initialized" in pending.json()["detail"]