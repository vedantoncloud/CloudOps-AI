from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_evidence_openapi_locks_lease_seconds_contract():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationEvidence"]
    lease_seconds = schema["properties"]["lease_seconds"]

    assert "lease_seconds" in schema["required"]
    assert lease_seconds["type"] == "number"
    assert lease_seconds["minimum"] == 0.0
    assert "default" not in lease_seconds
