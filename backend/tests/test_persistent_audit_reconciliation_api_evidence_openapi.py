from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_evidence_openapi_locks_numeric_constraints():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationEvidence"]

    assert set(schema["required"]) == {
        "lease_seconds",
        "pending_count",
        "active_count",
        "stale_count",
    }

    properties = schema["properties"]

    assert properties["lease_seconds"]["minimum"] == 0.0
    assert properties["pending_count"]["minimum"] == 0
    assert properties["active_count"]["minimum"] == 0
    assert properties["stale_count"]["minimum"] == 0