from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_value_error_matches_declared_503_contract(monkeypatch):
    def fail():
        raise ValueError("internal reconciliation failure")

    monkeypatch.setattr(reconciliation_api, "_reconciliation", fail)

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get("/autonomy/audit/reconciliation")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Persistent audit reconciliation is unavailable"
    }

    operation = app.openapi()["paths"]["/autonomy/audit/reconciliation"]["get"]
    assert "503" in operation["responses"]
    assert operation["responses"]["503"]["description"] == (
        "Persistent audit reconciliation is unavailable"
    )
