from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_classifies_mixed_active_and_stale_claims(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claims = [
        (
            "run-mixed-active",
            {"source": "mixed-active"},
            60,
        ),
        (
            "run-mixed-stale",
            {"source": "mixed-stale"},
            600,
        ),
    ]

    for run_id, evidence, age_seconds in claims:
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

    assert body["count"] == 2
    assert body["active_count"] == 1
    assert body["stale_count"] == 1
    assert body["read_only"] is True

    items = {
        item["run_id"]: item
        for item in body["items"]
    }

    assert set(items) == {
        "run-mixed-active",
        "run-mixed-stale",
    }

    active = items["run-mixed-active"]
    assert active["status"] == "active"
    assert active["age_seconds"] < 300.0
    assert active["evidence"] == {
        "source": "mixed-active"
    }

    stale = items["run-mixed-stale"]
    assert stale["status"] == "stale"
    assert stale["age_seconds"] >= 300.0
    assert stale["evidence"] == {
        "source": "mixed-stale"
    }

    assert body["evidence"]["pending_count"] == 2
    assert body["evidence"]["active_count"] == 1
    assert body["evidence"]["stale_count"] == 1

    assert store.contains(
        "run-mixed-active",
        "recovery_completed",
    ) is True
    assert store.contains(
        "run-mixed-stale",
        "recovery_completed",
    ) is True
