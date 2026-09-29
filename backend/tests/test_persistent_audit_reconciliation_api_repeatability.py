from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

    claimed_at = (datetime.now(timezone.utc) - timedelta(seconds=60)).timestamp()

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

    first_body = first.json()
    second_body = second.json()

    assert first_body["count"] == second_body["count"] == 1
    assert first_body["active_count"] == second_body["active_count"] == 1
    assert first_body["stale_count"] == second_body["stale_count"] == 0
    assert first_body["read_only"] is True
    assert second_body["read_only"] is True

    first_item = first_body["items"][0]
    second_item = second_body["items"][0]

    assert first_item["run_id"] == second_item["run_id"] == "run-repeatable"
    assert (
        first_item["event_type"]
        == second_item["event_type"]
        == "recovery_completed"
    )
    assert first_item["status"] == second_item["status"] == "active"
    assert first_item["claimed_at"] == second_item["claimed_at"] == claimed_at
    assert first_item["evidence"] == second_item["evidence"] == {
        "source": "api-repeatability"
    }

    assert second_item["age_seconds"] >= first_item["age_seconds"]

    assert first_body["evidence"]["store"] == "sqlite"
    assert second_body["evidence"]["store"] == "sqlite"
    assert first_body["evidence"]["read_only"] is True
    assert second_body["evidence"]["read_only"] is True
    assert first_body["evidence"]["lease_seconds"] == 300.0
    assert second_body["evidence"]["lease_seconds"] == 300.0

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

