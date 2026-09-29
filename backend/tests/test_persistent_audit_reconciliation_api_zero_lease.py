from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_marks_pending_claim_stale_with_zero_lease(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    result = store.claim(
        run_id="run-zero-lease",
        event_type="recovery_completed",
        evidence={"source": "zero-lease"},
    )
    assert result.emitted is True

    claimed_at = datetime.now(timezone.utc).timestamp()

    with store._connect() as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?, status = 'pending'
            WHERE run_id = ?
            """,
            (claimed_at, "run-zero-lease"),
        )

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )
    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_LEASE_SECONDS",
        0.0,
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["count"] == 1
    assert body["active_count"] == 0
    assert body["stale_count"] == 1
    assert body["items"][0]["status"] == "stale"
    assert body["evidence"]["lease_seconds"] == 0.0
