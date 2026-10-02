from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def _client():
    app = FastAPI()
    app.include_router(reconciliation_api.router)
    return TestClient(app, raise_server_exceptions=False)


def test_unavailable_database_returns_503(monkeypatch, tmp_path):
    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(tmp_path / "missing" / "audit.db"),
    )

    response = _client().get("/autonomy/audit/reconciliation")

    assert response.status_code == 503
    assert "detail" in response.json()


def test_corrupt_database_returns_503(monkeypatch, tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a valid sqlite database")

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )

    response = _client().get("/autonomy/audit/reconciliation")

    assert response.status_code == 503
    assert "detail" in response.json()
