from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_preserves_mixed_pending_claims(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claims = [
        ("run-readonly-active", 60, {"source": "active"}),
        ("run-readonly-stale", 600, {"source": "stale"}),
    ]

    for run_id, age_seconds, evidence in claims:
        result = store.claim(
            run_id=run_id,
            event_type="recovery_completed",
            evidence=evidence,
        )
        assert result.emitted is True

        claimed_at = (
            datetime.now(timezone.utc)
            - timedelta(seconds=age_seconds)
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
                    run_id,
                    "recovery_completed",
                ),
            )

    def snapshot():
        with store._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, event_type, status, claimed_at
                FROM audit_idempotency
                ORDER BY run_id, event_type
                """
            ).fetchall()
        return [
            tuple(row)
            for row in rows
        ]

    before = snapshot()

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
    assert response.json()["count"] == 2

    after = snapshot()

    assert after == before

    for run_id, _, _ in claims:
        assert store.contains(
            run_id,
            "recovery_completed",
        ) is True
