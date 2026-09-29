from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_returns_multiple_pending_claims(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claims = [
        (
            "run-multi-1",
            "recovery_completed",
            {"source": "multi-1"},
        ),
        (
            "run-multi-2",
            "recovery_completed",
            {"source": "multi-2"},
        ),
    ]

    for run_id, event_type, evidence in claims:
        result = store.claim(
            run_id=run_id,
            event_type=event_type,
            evidence=evidence,
        )
        assert result.emitted is True

    claimed_at = (
        datetime.now(timezone.utc) - timedelta(seconds=60)
    ).timestamp()

    with store._connect() as connection:
        for run_id, event_type, _ in claims:
            connection.execute(
                """
                UPDATE audit_idempotency
                SET claimed_at = ?, status = 'pending'
                WHERE run_id = ? AND event_type = ?
                """,
                (
                    claimed_at,
                    run_id,
                    event_type,
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
    assert body["active_count"] == 2
    assert body["stale_count"] == 0
    assert body["read_only"] is True

    items = {
        item["run_id"]: item
        for item in body["items"]
    }

    assert set(items) == {
        "run-multi-1",
        "run-multi-2",
    }

    assert items["run-multi-1"]["event_type"] == "recovery_completed"
    assert items["run-multi-1"]["status"] == "active"
    assert items["run-multi-1"]["evidence"] == {
        "source": "multi-1"
    }

    assert items["run-multi-2"]["event_type"] == "recovery_completed"
    assert items["run-multi-2"]["status"] == "active"
    assert items["run-multi-2"]["evidence"] == {
        "source": "multi-2"
    }

    assert body["evidence"]["pending_count"] == 2
    assert body["evidence"]["active_count"] == 2
    assert body["evidence"]["stale_count"] == 0

    assert store.contains(
        "run-multi-1",
        "recovery_completed",
    ) is True
    assert store.contains(
        "run-multi-2",
        "recovery_completed",
    ) is True
