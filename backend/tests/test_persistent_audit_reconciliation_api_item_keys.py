from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_exposes_stable_item_keys(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    result = store.claim(
        run_id="run-item-schema",
        event_type="recovery_completed",
        evidence={"source": "schema"},
    )
    assert result.emitted is True

    claimed_at = (
        datetime.now(timezone.utc) - timedelta(seconds=30)
    ).timestamp()

    with store._connect() as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?, status = 'pending'
            WHERE run_id = ?
            """,
            (claimed_at, "run-item-schema"),
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

    assert response.status_code == 200

    item = response.json()["items"][0]

    assert set(item.keys()) == {
        "run_id",
        "event_type",
        "status",
        "claimed_at",
        "age_seconds",
        "evidence",
    }
