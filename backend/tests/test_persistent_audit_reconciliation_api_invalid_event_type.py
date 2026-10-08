from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_maps_missing_event_type_to_503(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    store.claim(
        run_id="valid-run",
        event_type="recovery_completed",
        evidence={"source": "invalid-event"},
    )

    with store._connect() as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET event_type = ''
            WHERE run_id = ?
            """,
            ("valid-run",),
        )

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

    assert response.status_code == 503
    assert response.json()["detail"] == "Persistent audit reconciliation is unavailable"
