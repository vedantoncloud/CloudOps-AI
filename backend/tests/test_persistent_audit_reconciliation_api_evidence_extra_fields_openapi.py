from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_evidence_openapi_allows_additional_properties():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    schema = app.openapi()["components"]["schemas"]["AuditReconciliationEvidence"]

    assert schema["additionalProperties"] is True
