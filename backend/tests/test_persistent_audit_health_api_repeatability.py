from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def test_repeated_health_requests_are_identical(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    client = build_client(monkeypatch, path)

    first = client.get("/autonomy/audit/health")
    second = client.get("/autonomy/audit/health")
    third = client.get("/autonomy/audit/health")

    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json() == second.json() == third.json()


def test_repeated_pending_requests_are_identical(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("run-z", "recovery_failed", {"action_id": "z"})
    store.claim("run-a", "recovery_failed", {"action_id": "a"})

    client = build_client(monkeypatch, path)

    first = client.get("/autonomy/audit/pending")
    second = client.get("/autonomy/audit/pending")
    third = client.get("/autonomy/audit/pending")

    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json() == second.json() == third.json()


def test_empty_store_has_stable_zero_count_contract(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    client = build_client(monkeypatch, path)

    health = client.get("/autonomy/audit/health")
    pending = client.get("/autonomy/audit/pending")

    assert health.status_code == pending.status_code == 200

    health_body = health.json()
    pending_body = pending.json()

    assert health_body["total_claims"] == 0
    assert health_body["pending_claims"] == 0
    assert health_body["emitted_claims"] == 0
    assert health_body["evidence"]["consistent"] is True

    assert pending_body == {
        "count": 0,
        "pending": [],
        "read_only": True,
    }


def test_repeated_reads_do_not_change_persistent_state(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    client = build_client(monkeypatch, path)

    before = client.get("/autonomy/audit/health").json()

    for _ in range(5):
        assert client.get("/autonomy/audit/health").status_code == 200
        assert client.get("/autonomy/audit/pending").status_code == 200

    after = client.get("/autonomy/audit/health").json()

    assert before == after
    assert after["total_claims"] == 1
    assert after["pending_claims"] == 1
    assert after["emitted_claims"] == 0
