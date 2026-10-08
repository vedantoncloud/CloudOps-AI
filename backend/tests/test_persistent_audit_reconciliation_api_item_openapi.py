from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_item_openapi_locks_status_enum():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationItemResponse"]

    assert schema["properties"]["status"]["enum"] == ["active", "stale"]


def test_reconciliation_item_openapi_locks_numeric_constraints():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationItemResponse"]
    properties = schema["properties"]

    assert properties["claimed_at"]["minimum"] == 0.0
    assert properties["age_seconds"]["minimum"] == 0.0