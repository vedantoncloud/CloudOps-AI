from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_health_api import router


class FailingConnection:
    def __init__(self):
        self.closed = False

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("simulated read failure")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("method_name", ["inspect", "list_pending"])
def test_checker_wraps_sqlite_read_errors_and_closes_connection(
    tmp_path, monkeypatch, method_name
):
    connection = FailingConnection()

    monkeypatch.setattr(
        "autonomy.persistent_audit_health.sqlite3.connect",
        lambda *args, **kwargs: connection,
    )

    checker = PersistentAuditHealthChecker(tmp_path / "audit.db")

    with pytest.raises(
        ValueError,
        match="Persistent audit idempotency store is not initialized",
    ):
        getattr(checker, method_name)()

    assert connection.closed is True


@pytest.mark.parametrize(
    "endpoint",
    [
        "/autonomy/audit/health",
        "/autonomy/audit/pending",
    ],
)
def test_api_returns_consistent_503_on_sqlite_read_failure(
    tmp_path, monkeypatch, endpoint
):
    connection = FailingConnection()

    monkeypatch.setattr(
        "autonomy.persistent_audit_health_api.DEFAULT_DB_PATH",
        str(tmp_path / "audit.db"),
    )

    monkeypatch.setattr(
        "autonomy.persistent_audit_health.sqlite3.connect",
        lambda *args, **kwargs: connection,
    )

    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get(endpoint)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Persistent audit idempotency store is not initialized"
    }
    assert connection.closed is True