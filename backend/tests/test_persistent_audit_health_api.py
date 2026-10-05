from __future__ import annotations

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


def test_health_endpoint_returns_persistent_state(tmp_path: Path, monkeypatch):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    pending = store.claim(
        "run-1",
        "recovery_failed",
        {"action_id": "a-1"},
    )
    emitted = store.claim(
        "run-2",
        "recovery_completed",
        {"action_id": "a-2"},
    )
    assert store.mark_emitted(
        "run-2",
        "recovery_completed",
        emitted.claim_token,
    )

    response = build_client(monkeypatch, path).get("/autonomy/audit/health")

    assert response.status_code == 200
    body = response.json()
    assert body["total_claims"] == 2
    assert body["pending_claims"] == 1
    assert body["emitted_claims"] == 1
    assert body["evidence"]["read_only"] is True


def test_pending_endpoint_is_read_only(tmp_path: Path, monkeypatch):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)
    store.claim("run-2", "recovery_failed", {"action_id": "a-2"})
    before = PersistentAuditHealthChecker(path).inspect()

    response = build_client(monkeypatch, path).get("/autonomy/audit/pending")

    after = PersistentAuditHealthChecker(path).inspect()

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["read_only"] is True
    assert before == after


def test_health_endpoint_reports_uninitialized_store(
    tmp_path: Path,
    monkeypatch,
):
    response = build_client(
        monkeypatch,
        tmp_path / "missing.db",
    ).get("/autonomy/audit/health")

    assert response.status_code == 503
    assert "not initialized" in response.json()["detail"]


def test_pending_endpoint_reports_uninitialized_store(
    tmp_path: Path,
    monkeypatch,
):
    response = build_client(
        monkeypatch,
        tmp_path / "missing.db",
    ).get("/autonomy/audit/pending")

    assert response.status_code == 503
    assert "not initialized" in response.json()["detail"]


def test_health_endpoint_hides_database_error_details(tmp_path: Path, monkeypatch):
    path = tmp_path / "broken.db"
    path.write_text("not a sqlite database", encoding="utf-8")

    response = build_client(monkeypatch, path).get("/autonomy/audit/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "Persistent audit idempotency store is not initialized"
    assert "not a database" not in response.text


def test_pending_endpoint_hides_database_error_details(tmp_path: Path, monkeypatch):
    path = tmp_path / "broken.db"
    path.write_text("not a sqlite database", encoding="utf-8")

    response = build_client(monkeypatch, path).get("/autonomy/audit/pending")

    assert response.status_code == 503
    assert response.json()["detail"] == "Persistent audit idempotency store is not initialized"
    assert "not a database" not in response.text


def test_health_endpoint_supports_special_characters_in_database_path(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "audit #1 test.db"
    store = PersistentAuditIdempotencyStore(path)
    store.claim("run-special", "recovery_failed", {"source": "api-path-test"})

    response = build_client(monkeypatch, path).get("/autonomy/audit/health")

    assert response.status_code == 200
    body = response.json()
    assert body["total_claims"] == 1
    assert body["pending_claims"] == 1
    assert body["evidence"]["read_only"] is True
