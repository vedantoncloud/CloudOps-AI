from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_marks_claim_stale_at_exact_lease_boundary(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claim = store.claim(
        run_id="run-lease-boundary",
        event_type="recovery_completed",
        evidence={"source": "lease-boundary"},
    )

    assert claim.emitted is True

    claimed_at = (
        datetime.now(timezone.utc) - timedelta(seconds=300)
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
                "run-lease-boundary",
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
    assert body["active_count"] == 0
    assert body["stale_count"] == 1

    item = body["items"][0]

    assert item["run_id"] == "run-lease-boundary"
    assert item["event_type"] == "recovery_completed"
    assert item["status"] == "stale"
    assert item["age_seconds"] >= 300.0
    assert item["evidence"] == {"source": "lease-boundary"}

    assert store.contains(
        "run-lease-boundary",
        "recovery_completed",
    ) is True
