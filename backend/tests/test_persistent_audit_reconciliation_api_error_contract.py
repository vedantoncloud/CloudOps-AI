from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def _app():
    app = FastAPI()
    app.include_router(reconciliation_api.router)
    return app


def test_reconciliation_api_hides_unexpected_internal_error(monkeypatch):
    class BrokenReconciliation:
        def __init__(self, store, *, lease_seconds):
            self.store = store
            self.lease_seconds = lease_seconds

        def inspect(self):
            raise RuntimeError("secret database path / internal failure")

    monkeypatch.setattr(
        reconciliation_api,
        "PersistentAuditReconciliation",
        BrokenReconciliation,
    )

    response = TestClient(
        _app(),
        raise_server_exceptions=False,
    ).get("/autonomy/audit/reconciliation")

    assert response.status_code == 500
    assert "secret database path" not in response.text


def test_reconciliation_api_maps_os_errors_to_503(monkeypatch):
    class BrokenReconciliation:
        def __init__(self, store, *, lease_seconds):
            self.store = store
            self.lease_seconds = lease_seconds

        def inspect(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(
        reconciliation_api,
        "PersistentAuditReconciliation",
        BrokenReconciliation,
    )

    response = TestClient(_app()).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Persistent audit reconciliation is unavailable"
    )


def test_reconciliation_api_maps_value_errors_to_503(monkeypatch):
    class BrokenReconciliation:
        def __init__(self, store, *, lease_seconds):
            self.store = store
            self.lease_seconds = lease_seconds

        def inspect(self):
            raise ValueError("invalid internal state")

    monkeypatch.setattr(
        reconciliation_api,
        "PersistentAuditReconciliation",
        BrokenReconciliation,
    )

    response = TestClient(_app()).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Persistent audit reconciliation is unavailable"
    )
