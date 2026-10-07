from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_declares_503_response():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    operation = app.openapi()["paths"]["/autonomy/audit/reconciliation"]["get"]

    assert "503" in operation["responses"]

    response = operation["responses"]["503"]

    assert response["description"] == (
        "Persistent audit reconciliation is unavailable"
    )
