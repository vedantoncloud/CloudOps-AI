from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_200_openapi_locks_read_only_true():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = app.openapi()["paths"]["/autonomy/audit/reconciliation"]["get"][
        "responses"
    ]["200"]

    schema = response["content"]["application/json"]["schema"]
    assert schema["properties"]["read_only"] == {"const": True}