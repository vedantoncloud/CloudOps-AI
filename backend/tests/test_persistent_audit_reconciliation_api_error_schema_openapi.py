from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_503_openapi_declares_error_schema():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    operation = app.openapi()["paths"]["/autonomy/audit/reconciliation"]["get"]

    response = operation["responses"]["503"]

    assert response["description"] == (
        "Persistent audit reconciliation is unavailable"
    )

    schema = response["content"]["application/json"]["schema"]

    assert schema["$ref"] == (
        "#/components/schemas/AuditReconciliationErrorResponse"
    )


def test_reconciliation_api_error_schema_requires_detail():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schemas = app.openapi()["components"]["schemas"]
    error_schema = schemas["AuditReconciliationErrorResponse"]

    assert error_schema["type"] == "object"
    assert error_schema["required"] == ["detail"]
    assert error_schema["properties"]["detail"]["type"] == "string"
