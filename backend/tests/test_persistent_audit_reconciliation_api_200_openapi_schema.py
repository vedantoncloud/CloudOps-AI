from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_200_openapi_schema_is_strict():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    operation = app.openapi()["paths"]["/autonomy/audit/reconciliation"]["get"]

    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert schema["$ref"].endswith("/AuditReconciliationResponse")

    model_schema = app.openapi()["components"]["schemas"][
        "AuditReconciliationResponse"
    ]

    assert model_schema["type"] == "object"
    assert set(model_schema["required"]) == {
        "count",
        "active_count",
        "stale_count",
        "items",
        "evidence",
        "read_only",
    }
    assert model_schema["properties"]["count"]["minimum"] == 0
    assert model_schema["properties"]["active_count"]["minimum"] == 0
    assert model_schema["properties"]["stale_count"]["minimum"] == 0
    assert model_schema["properties"]["read_only"]["const"] is True
