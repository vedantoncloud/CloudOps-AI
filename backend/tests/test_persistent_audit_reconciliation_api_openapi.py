from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_openapi_declares_response_schema():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()
    operation = schema["paths"]["/autonomy/audit/reconciliation"]["get"]

    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/AuditReconciliationResponse")


def test_reconciliation_api_openapi_exposes_response_models():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schemas = app.openapi()["components"]["schemas"]

    assert "AuditReconciliationResponse" in schemas
    assert "AuditReconciliationItemResponse" in schemas
    assert "AuditReconciliationEvidence" in schemas


def test_reconciliation_api_openapi_requires_stable_response_fields():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schemas = app.openapi()["components"]["schemas"]

    response_schema = schemas["AuditReconciliationResponse"]
    assert set(response_schema["required"]) == {
        "count",
        "active_count",
        "stale_count",
        "items",
        "evidence",
        "read_only",
    }

    item_schema = schemas["AuditReconciliationItemResponse"]
    assert set(item_schema["required"]) == {
        "run_id",
        "event_type",
        "status",
        "claimed_at",
        "age_seconds",
        "evidence",
    }
