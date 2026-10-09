from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_evidence_openapi_store_is_optional():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationEvidence"]

    assert "store" not in schema["required"]
