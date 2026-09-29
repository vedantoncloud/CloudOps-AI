from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_preserves_distinct_event_types_for_same_run(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    events = [
        (
            "recovery_completed",
            {"source": "recovery"},
        ),
        (
            "verification_completed",
            {"source": "verification"},
        ),
    ]

    for event_type, evidence in events:
        result = store.claim(
            run_id="run-distinct-events",
            event_type=event_type,
            evidence=evidence,
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
            (
                claimed_at,
                "run-distinct-events",
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

    items = {
        item["event_type"]: item
        for item in body["items"]
    }

    assert set(items) == {
        "recovery_completed",
        "verification_completed",
    }

    assert items["recovery_completed"]["run_id"] == (
        "run-distinct-events"
    )
    assert items["recovery_completed"]["status"] == "active"
    assert items["recovery_completed"]["evidence"] == {
        "source": "recovery"
    }

    assert items["verification_completed"]["run_id"] == (
        "run-distinct-events"
    )
    assert items["verification_completed"]["status"] == "active"
    assert items["verification_completed"]["evidence"] == {
        "source": "verification"
    }

    assert body["evidence"]["pending_count"] == 2
    assert body["evidence"]["active_count"] == 2
    assert body["evidence"]["stale_count"] == 0
