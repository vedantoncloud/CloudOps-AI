from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_preserves_classification_across_reads(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    result = store.claim(
        run_id="run-stable-classification",
        event_type="recovery_completed",
        evidence={"source": "classification"},
    )
    assert result.emitted is True

    claimed_at = (
        datetime.now(timezone.utc) - timedelta(seconds=60)
    ).timestamp()

    with store._connect() as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?, status = 'pending'
            WHERE run_id = ?
            """,
            (claimed_at, "run-stable-classification"),
        )

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    client = TestClient(app)

    first = client.get("/autonomy/audit/reconciliation").json()
    second = client.get("/autonomy/audit/reconciliation").json()

    assert first["active_count"] == 1
    assert first["stale_count"] == 0
    assert second["active_count"] == 1
    assert second["stale_count"] == 0

    assert first["items"][0]["status"] == "active"
    assert second["items"][0]["status"] == "active"
    assert second["items"][0]["age_seconds"] >= (
        first["items"][0]["age_seconds"]
    )
