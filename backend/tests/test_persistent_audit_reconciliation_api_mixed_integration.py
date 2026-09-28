from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_reconciliation_api_mixed_active_and_stale(monkeypatch, tmp_path):
    db_path = tmp_path / "mixed.db"
    store = PersistentAuditIdempotencyStore(db_path)

    store.claim("run-active", "event.active", {"kind": "active"})
    store.claim("run-stale", "event.stale", {"kind": "stale"})

    # Ensure the schema is initialized before directly manipulating the
    # persisted claim timestamps for deterministic classification.
    store.contains("run-active", "event.active")
    store.contains("run-stale", "event.stale")

    with store._connect() as connection:
        connection.execute(
            """
            UPDATE audit_claims
            SET claimed_at = ?, status = 'pending'
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
                now=1000.0,
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

    assert payload["evidence"]["pending_count"] == 2
    assert payload["evidence"]["active_count"] == 1
    assert payload["evidence"]["stale_count"] == 1
    assert payload["evidence"]["read_only"] is True
