from __future__ import annotations

from fastapi import FastAPI

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_200_openapi_locks_read_only_true():
    app = FastAPI()
    app.include_router(reconciliation_api.router)

    openapi = app.openapi()
    response = openapi["paths"]["/autonomy/audit/reconciliation"]["get"][
        "responses"
    ]["200"]

    schema_ref = response["content"]["application/json"]["schema"]["$ref"]
    schema_name = schema_ref.rsplit("/", 1)[-1]
    schema = openapi["components"]["schemas"][schema_name]

    read_only = schema["properties"]["read_only"]

    assert read_only["const"] is True