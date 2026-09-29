from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api


def test_reconciliation_api_exposes_stable_top_level_keys(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 200

    body = response.json()

    assert set(body.keys()) == {
        "count",
        "active_count",
        "stale_count",
        "items",
        "evidence",
        "read_only",
    }
