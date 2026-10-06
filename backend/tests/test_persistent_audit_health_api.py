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


def test_health_endpoint_exposes_malformed_evidence_diagnostic(
    tmp_path: Path,
    monkeypatch,
):
    import sqlite3

    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)
    store.claim("run-malformed", "recovery_failed", {"source": "test"})

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE audit_idempotency SET evidence_json = ? WHERE run_id = ?",
            ("not-json", "run-malformed"),
        )
        connection.commit()

    response = build_client(monkeypatch, path).get("/autonomy/audit/health")

    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["malformed_evidence_claims"] == 1
    assert body["evidence"]["consistent"] is True


def test_audit_health_openapi_exposes_response_contract():
    app = FastAPI()
    app.include_router(router)

    schema = app.openapi()
    health = schema["paths"]["/autonomy/audit/health"]["get"]
    pending = schema["paths"]["/autonomy/audit/pending"]["get"]

    assert health["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/AuditHealthResponse")

    assert pending["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/AuditPendingResponse")


def test_audit_health_response_model_rejects_negative_counts():
    from pydantic import ValidationError
    from autonomy.persistent_audit_health_api import AuditHealthResponse

    try:
        AuditHealthResponse(
            path="audit.db",
            total_claims=-1,
            pending_claims=0,
            emitted_claims=0,
            evidence_conflicts=0,
            evidence={},
        )
    except ValidationError:
        return

    raise AssertionError("Negative health counters must be rejected")


def test_audit_pending_response_model_rejects_negative_count():
    from pydantic import ValidationError
    from autonomy.persistent_audit_health_api import AuditPendingResponse

    try:
        AuditPendingResponse(
            count=-1,
            pending=[],
            read_only=True,
        )
    except ValidationError:
        return

    raise AssertionError("Negative pending count must be rejected")


def test_audit_health_openapi_requires_health_fields():
    app = FastAPI()
    app.include_router(router)

    schema = app.openapi()
    health_schema = schema["components"]["schemas"]["AuditHealthResponse"]

    assert set(health_schema["required"]) == {
        "path",
        "total_claims",
        "pending_claims",
        "emitted_claims",
        "evidence_conflicts",
        "evidence",
    }


def test_audit_pending_openapi_requires_pending_fields():
    app = FastAPI()
    app.include_router(router)

    schema = app.openapi()
    pending_schema = schema["components"]["schemas"]["AuditPendingResponse"]

    assert set(pending_schema["required"]) == {
        "count",
        "pending",
        "read_only",
    }


def test_pending_endpoint_returns_typed_pending_items(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)
    store.claim(
        "run-typed",
        "recovery_failed",
        {"action_id": "typed-1"},
    )

    response = build_client(monkeypatch, path).get("/autonomy/audit/pending")

    assert response.status_code == 200

    item = response.json()["pending"][0]
    assert item["run_id"] == "run-typed"
    assert item["event_type"] == "recovery_failed"
    assert isinstance(item["claimed_at"], float)
    assert item["evidence"] == {"action_id": "typed-1"}


def test_audit_pending_openapi_locks_pending_item_fields():
    app = FastAPI()
    app.include_router(router)

    schema = app.openapi()

    item_schema = schema["components"]["schemas"]["AuditPendingItem"]

    assert set(item_schema["required"]) == {
        "run_id",
        "event_type",
        "claimed_at",
        "evidence",
    }
