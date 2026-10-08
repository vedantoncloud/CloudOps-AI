from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_evidence_openapi_locks_read_only_default():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationEvidence"]
    read_only = schema["properties"]["read_only"]

    assert read_only["default"] is False
