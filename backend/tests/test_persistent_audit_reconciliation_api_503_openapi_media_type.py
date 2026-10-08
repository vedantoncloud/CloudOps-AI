from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_503_openapi_uses_json_media_type():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = app.openapi()["paths"]["/autonomy/audit/reconciliation"]["get"][
        "responses"
    ]["503"]

    assert set(response["content"]) == {"application/json"}