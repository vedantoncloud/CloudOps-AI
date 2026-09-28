from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_reconciliation_api_mixed_active_and_stale(monkeypatch, tmp_path):
    db_path = tmp_path / "mixed.db"
    store = PersistentAuditIdempotencyStore(db_path)

    active_claim = store.claim(
        "run-active",
        "event.active",
        {"kind": "active"},
    )
    stale_claim = store.claim(
        "run-stale",
        "event.stale",
        {"kind": "stale"},
    )

    assert active_claim.emitted is True
    assert stale_claim.emitted is True

    # Production schema/table name is audit_idempotency.
    with store._connect() as connection:
        rows = connection.execute(
            """
            SELECT run_id, event_type, status
            FROM audit_idempotency
            ORDER BY run_id, event_type
            """
        ).fetchall()

        assert rows == [
            ("run-active", "event.active", "pending"),
            ("run-stale", "event.stale", "pending"),
        ]

        # Make only the second claim stale at fixed time 1000.0.
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?
            WHERE run_id = ? AND event_type = ?
            """,
            (700.0, "run-stale", "event.stale"),
        )
        connection.commit()

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )

    class FixedNowReconciliation(PersistentAuditReconciliation):
        def __init__(self, store, lease_seconds=300.0):
            super().__init__(
                store,
                lease_seconds=lease_seconds,
                now=__import__("datetime").datetime(
                    1970,
                    1,
                    1,
                    0,
                    16,
                    40,
                    tzinfo=__import__("datetime").timezone.utc,
                ),
            )

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

    payload = response.json()

    assert payload["count"] == 2
    assert payload["active_count"] == 1
    assert payload["stale_count"] == 1
    assert payload["read_only"] is True

    assert [
        (item["run_id"], item["event_type"], item["status"])
        for item in payload["items"]
    ] == [
        ("run-active", "event.active", "active"),
        ("run-stale", "event.stale", "stale"),
    ]

    assert payload["evidence"] == {
        "store": "sqlite",
        "read_only": True,
        "lease_seconds": 300.0,
        "pending_count": 2,
        "active_count": 1,
        "stale_count": 1,
    }

    # Reconciliation must remain read-only.
    with store._connect() as connection:
        rows_after = connection.execute(
            """
            SELECT run_id, event_type, status, claimed_at
            FROM audit_idempotency
            ORDER BY run_id, event_type
            """
        ).fetchall()

    assert rows_after == [
        ("run-active", "event.active", "pending", rows_after[0][3]),
        ("run-stale", "event.stale", "pending", 700.0),
    ]
