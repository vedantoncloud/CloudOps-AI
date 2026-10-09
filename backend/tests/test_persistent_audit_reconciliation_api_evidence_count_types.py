from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_evidence_openapi_locks_count_field_types():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationEvidence"]
    properties = schema["properties"]

    for field in ("pending_count", "active_count", "stale_count"):
        assert properties[field]["type"] == "integer"
