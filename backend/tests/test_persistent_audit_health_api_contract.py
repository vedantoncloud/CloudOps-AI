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


def test_health_api_response_contract(tmp_path, monkeypatch):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    response = build_client(monkeypatch, path).get(
        "/autonomy/audit/health"
    )

    assert response.status_code == 200

    body = response.json()

    assert set(body) == {
        "path",
        "total_claims",
        "pending_claims",
        "emitted_claims",
        "evidence_conflicts",
        "evidence",
    }

    assert body["total_claims"] == (
        body["pending_claims"] + body["emitted_claims"]
    )
    assert body["evidence_conflicts"] == 0
    assert body["evidence"]["store"] == "sqlite"
    assert body["evidence"]["read_only"] is True
    assert body["evidence"]["consistent"] is True


def test_pending_api_response_contract_and_order(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("run-z", "recovery_failed", {"action_id": "z"})
    store.claim("run-a", "recovery_failed", {"action_id": "a"})

    response = build_client(monkeypatch, path).get(
        "/autonomy/audit/pending"
    )

    assert response.status_code == 200

    body = response.json()

    assert set(body) == {"count", "pending", "read_only"}
    assert body["count"] == len(body["pending"]) == 2
    assert body["read_only"] is True

    assert [item["run_id"] for item in body["pending"]] == [
        "run-a",
        "run-z",
    ]

    for item in body["pending"]:
        assert set(item) == {
            "run_id",
            "event_type",
            "claimed_at",
            "evidence",
        }
        assert isinstance(item["run_id"], str)
        assert isinstance(item["event_type"], str)
        assert isinstance(item["claimed_at"], (int, float))
        assert isinstance(item["evidence"], dict)


def test_health_and_pending_endpoints_preserve_read_only_state(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    client = build_client(monkeypatch, path)

    before = client.get("/autonomy/audit/health").json()
    pending = client.get("/autonomy/audit/pending").json()
    after = client.get("/autonomy/audit/health").json()

    assert before == after
    assert pending["read_only"] is True
    assert pending["count"] == before["pending_claims"]
