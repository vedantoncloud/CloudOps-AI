from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_503_response_matches_model(monkeypatch):
    def fail():
        raise OSError("database unavailable")

    monkeypatch.setattr(reconciliation_api, "_reconciliation", fail)

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get("/autonomy/audit/reconciliation")

    assert response.status_code == 503

    parsed = reconciliation_api.AuditReconciliationErrorResponse.model_validate(
        response.json()
    )

    assert parsed.detail == "Persistent audit reconciliation is unavailable"
