from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_503_openapi_schema_is_strict():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["paths"]["/autonomy/audit/reconciliation"]["get"][
        "responses"
    ]["503"]["content"]["application/json"]["schema"]

    assert schema["$ref"].endswith("/AuditReconciliationErrorResponse")

    model_schema = app.openapi()["components"]["schemas"][
        "AuditReconciliationErrorResponse"
    ]

    assert model_schema["type"] == "object"
    assert model_schema["required"] == ["detail"]
    assert model_schema["properties"]["detail"]["type"] == "string"
    assert model_schema["properties"]["detail"]["minLength"] == 1
