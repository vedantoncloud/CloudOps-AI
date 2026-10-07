from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def _schema():
    app = FastAPI()
    app.include_router(reconciliation_api.router)
    return app.openapi()["components"]["schemas"]


def test_reconciliation_item_status_openapi_is_strict():
    schemas = _schema()

    status = schemas["AuditReconciliationItemResponse"]["properties"]["status"]

    assert status["type"] == "string"
    assert status["enum"] == ["active", "stale"]


def test_reconciliation_response_read_only_openapi_is_true_only():
    schemas = _schema()

    read_only = schemas["AuditReconciliationResponse"]["properties"]["read_only"]

    assert read_only["type"] == "boolean"
    assert read_only["const"] is True
