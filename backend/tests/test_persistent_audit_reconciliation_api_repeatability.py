from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_reconciliation_api_is_repeatable_for_unchanged_pending_claims(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"

    store = PersistentAuditIdempotencyStore(db_path)

    claim = store.claim(
        run_id="run-repeatable",
        event_type="recovery_completed",
        evidence={"source": "api-repeatability"},
    )

    assert claim.emitted is True

    claimed_at = datetime(
        2026,
        9,
        28,
        20,
        0,
        tzinfo=timezone.utc,
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
                "run-repeatable",
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

    client = TestClient(app)

    first = client.get(
        "/autonomy/audit/reconciliation"
    )

    second = client.get(
        "/autonomy/audit/reconciliation"
    )

    assert first.status_code == 200
    assert second.status_code == 200

    assert first.json() == second.json()

    body = first.json()

    assert body["count"] == 1
    assert body["active_count"] == 1
    assert body["stale_count"] == 0
    assert body["read_only"] is True

    assert body["items"][0]["run_id"] == (
        "run-repeatable"
    )

    assert body["items"][0]["event_type"] == (
        "recovery_completed"
    )

    assert body["items"][0]["status"] == "active"

    assert body["items"][0]["evidence"] == {
        "source": "api-repeatability"
    }

    with store._connect() as connection:
        row = connection.execute(
            """
            SELECT status, claimed_at
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            (
                "run-repeatable",
                "recovery_completed",
            ),
        ).fetchone()

    assert row[0] == "pending"
    assert row[1] == claimed_at
