from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_e2e_contract(monkeypatch, tmp_path):
    db_path = tmp_path / "e2e.db"
    store = PersistentAuditIdempotencyStore(db_path)

    store.claim(
        "run-e2e-active",
        "audit.active",
        {
            "source": "e2e",
            "kind": "active",
        },
    )

    store.claim(
        "run-e2e-stale",
        "audit.stale",
        {
            "source": "e2e",
            "kind": "stale",
        },
    )

    with store._connect() as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?
            WHERE run_id = ? AND event_type = ?
            """,
            (700.0, "run-e2e-stale", "audit.stale"),
        )
        connection.commit()

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )

    from datetime import datetime, timezone
    from autonomy.persistent_audit_reconciliation import (
        PersistentAuditReconciliation,
    )

    class FixedNowReconciliation(PersistentAuditReconciliation):
        def __init__(self, store, lease_seconds=300.0):
            super().__init__(
                store,
                lease_seconds=lease_seconds,
                now=datetime.fromtimestamp(
                    1000.0,
                    tz=timezone.utc,
                ),
            )

    monkeypatch.setattr(
        reconciliation_api,
        "PersistentAuditReconciliation",
        FixedNowReconciliation,
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    client = TestClient(app)

    response = client.get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 200

    body = response.json()

    # Top-level contract
    assert set(body) == {
        "count",
        "active_count",
        "stale_count",
        "items",
        "evidence",
        "read_only",
    }

    assert body["count"] == 2
    assert body["active_count"] == 1
    assert body["stale_count"] == 1
    assert body["read_only"] is True

    # Item contract
    assert len(body["items"]) == 2

    assert [
        (
            item["run_id"],
            item["event_type"],
            item["status"],
        )
        for item in body["items"]
    ] == [
        (
            "run-e2e-active",
            "audit.active",
            "active",
        ),
        (
            "run-e2e-stale",
            "audit.stale",
            "stale",
        ),
    ]

    for item in body["items"]:
        assert set(item) == {
            "run_id",
            "event_type",
            "status",
            "claimed_at",
            "age_seconds",
            "evidence",
        }

    # Evidence contract
    assert body["evidence"] == {
        "store": "sqlite",
        "read_only": True,
        "lease_seconds": 300.0,
        "pending_count": 2,
        "active_count": 1,
        "stale_count": 1,
    }

    assert body["items"][0]["age_seconds"] < 300
    assert body["items"][1]["age_seconds"] == 300

    # Read-only guarantee: database remains pending after API inspection.
    with store._connect() as connection:
        rows = connection.execute(
            """
            SELECT run_id, event_type, status, claimed_at
            FROM audit_idempotency
            ORDER BY run_id, event_type
            """
        ).fetchall()

    assert rows[0][0:3] == (
        "run-e2e-active",
        "audit.active",
        "pending",
    )

    assert rows[1] == (
        "run-e2e-stale",
        "audit.stale",
        "pending",
        700.0,
    )
