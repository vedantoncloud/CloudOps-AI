from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import (
    PersistentAuditReconciliation,
)


def test_reconciliation_api_real_mixed_active_and_stale(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"

    store = PersistentAuditIdempotencyStore(db_path)

    store.claim(
        "run-active",
        "recovery_completed",
        {
            "source": "mixed-integration",
            "run_id": "run-active",
        },
    )

    store.claim(
        "run-stale",
        "recovery_failed",
        {
            "source": "mixed-integration",
            "run_id": "run-stale",
        },
    )

    now = datetime(
        2026,
        9,
        28,
        20,
        0,
        tzinfo=timezone.utc,
    )

    active_time = now.timestamp() - 10
    stale_time = now.timestamp() - 301

    with store._connect() as connection:

        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?, status = 'pending'
            WHERE run_id = ? AND event_type = ?
            """,
            (
                active_time,
                "run-active",
                "recovery_completed",
            ),
        )

        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?, status = 'pending'
            WHERE run_id = ? AND event_type = ?
            """,
            (
                stale_time,
                "run-stale",
                "recovery_failed",
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

    class FixedNowReconciliation:

        def __init__(self, store, *, lease_seconds):
            self._delegate = PersistentAuditReconciliation(
                store,
                lease_seconds=lease_seconds,
                now=now,
            )

        def inspect(self):
            return self._delegate.inspect()

    monkeypatch.setattr(
        reconciliation_api,
        "PersistentAuditReconciliation",
        FixedNowReconciliation,
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

    assert items["run-active"]["status"] == "active"
    assert items["run-stale"]["status"] == "stale"

    assert body["evidence"]["pending_count"] == 2
    assert body["evidence"]["active_count"] == 1
    assert body["evidence"]["stale_count"] == 1

    with store._connect() as connection:

        rows = connection.execute(
            """
            SELECT run_id, event_type, status, claimed_at
            FROM audit_idempotency
            ORDER BY run_id, event_type
            """
        ).fetchall()

    assert rows == [
        (
            "run-active",
            "recovery_completed",
            "pending",
            active_time,
        ),
        (
            "run-stale",
            "recovery_failed",
            "pending",
            stale_time,
        ),
    ]
