from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main
import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_main_app_exposes_reconciliation_route_with_pending_claim(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    result = store.claim(
        run_id="run-main-app",
        event_type="recovery_completed",
        evidence={"source": "main-app"},
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
            WHERE run_id = ? AND event_type = ?
            """,
            (
                claimed_at,
                "run-main-app",
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

    response = TestClient(main.app).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["count"] == 1
    assert body["active_count"] == 1
    assert body["stale_count"] == 0

    item = body["items"][0]

    assert item["run_id"] == "run-main-app"
    assert item["event_type"] == "recovery_completed"
    assert item["status"] == "active"
    assert item["evidence"] == {
        "source": "main-app"
    }

    assert body["read_only"] is True
