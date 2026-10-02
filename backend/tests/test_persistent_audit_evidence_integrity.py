from __future__ import annotations

import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_health_api import router
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def build_client(monkeypatch, path):
    monkeypatch.setattr(
        "autonomy.persistent_audit_health_api.DEFAULT_DB_PATH",
        str(path),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_pending_api_preserves_malformed_evidence_as_raw_data(
    tmp_path, monkeypatch
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim(
        "malformed-run",
        "recovery_failed",
        {"action_id": "malformed"},
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET evidence_json = ?
            WHERE run_id = ? AND event_type = ?
            """,
            ("{invalid-json", "malformed-run", "recovery_failed"),
        )

    client = build_client(monkeypatch, path)

    first = client.get("/autonomy/audit/pending")
    second = client.get("/autonomy/audit/pending")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    body = first.json()
    assert body["count"] == 1
    assert body["read_only"] is True
    assert body["pending"][0]["run_id"] == "malformed-run"
    assert body["pending"][0]["evidence"] == {
        "raw": "{invalid-json"
    }


def test_pending_api_keeps_valid_json_evidence_structured(
    tmp_path, monkeypatch
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim(
        "valid-run",
        "recovery_failed",
        {"action_id": "valid", "source": "test"},
    )

    client = build_client(monkeypatch, path)
    response = client.get("/autonomy/audit/pending")

    assert response.status_code == 200
    item = response.json()["pending"][0]

    assert item["evidence"] == {
        "action_id": "valid",
        "source": "test",
    }


def test_pending_api_does_not_mutate_malformed_evidence_record(
    tmp_path, monkeypatch
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim(
        "stable-run",
        "recovery_failed",
        {"action_id": "stable"},
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET evidence_json = ?
            WHERE run_id = ?
            """,
            ("not-json", "stable-run"),
        )

    before = PersistentAuditHealthChecker(path).inspect()

    client = build_client(monkeypatch, path)
    first = client.get("/autonomy/audit/pending")
    second = client.get("/autonomy/audit/pending")

    after = PersistentAuditHealthChecker(path).inspect()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert before == after

    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            """
            SELECT evidence_json
            FROM audit_idempotency
            WHERE run_id = ?
            """,
            ("stable-run",),
        ).fetchone()[0]

    assert stored == "not-json"