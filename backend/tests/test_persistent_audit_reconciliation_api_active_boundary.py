from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_keeps_claim_active_just_inside_lease_boundary(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claim = store.claim(
        run_id="run-active-boundary",
        event_type="recovery_completed",
        evidence={"source": "active-boundary"},
    )

    assert claim.emitted is True

    claimed_at = (
        datetime.now(timezone.utc) - timedelta(seconds=299)
    ).timestamp()

    with store._connect() as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?, status = 'pending'
            WHERE run_id = ? AND event_type = ?
            """,
            (
                claimed_at,
                "run-active-boundary",
                "recovery_completed",
            ),
        )

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )
    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_LEASE_SECONDS",
        300.0,
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["count"] == 1
    assert body["active_count"] == 1
    assert body["stale_count"] == 0

    item = body["items"][0]

    assert item["run_id"] == "run-active-boundary"
    assert item["event_type"] == "recovery_completed"
    assert item["status"] == "active"
    assert item["age_seconds"] < 300.0
    assert item["evidence"] == {"source": "active-boundary"}

    assert store.contains(
        "run-active-boundary",
        "recovery_completed",
    ) is True
