from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_health_api as health_api


def build_client(monkeypatch, path):
    monkeypatch.setattr(health_api, "DEFAULT_DB_PATH", str(path))
    app = FastAPI()
    app.include_router(health_api.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "endpoint",
    [
        "/autonomy/audit/health",
        "/autonomy/audit/pending",
    ],
)
@pytest.mark.parametrize("failure_kind", ["missing_parent", "corrupt_database"])
def test_storage_failures_return_consistent_503(
    tmp_path,
    monkeypatch,
    endpoint,
    failure_kind,
):
    if failure_kind == "missing_parent":
        db_path = tmp_path / "missing" / "audit.db"
    else:
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"not a valid sqlite database")

    response = build_client(monkeypatch, db_path).get(endpoint)

    assert response.status_code == 503
    assert "not initialized" in response.json()["detail"]
