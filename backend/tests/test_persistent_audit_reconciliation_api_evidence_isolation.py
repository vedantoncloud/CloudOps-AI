from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_preserves_claim_evidence_without_cross_contamination(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claims = [
        (
            "run-evidence-a",
            {"source": "a", "action_id": "action-a"},
        ),
        (
            "run-evidence-b",
            {"source": "b", "action_id": "action-b"},
        ),
    ]

    for run_id, evidence in claims:
        result = store.claim(
            run_id=run_id,
            event_type="recovery_completed",
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
            WHERE status = 'pending'
            """,
            (claimed_at,),
        )

    monkeypatch.setattr(
        reconciliation_api,
        "DEFAULT_DB_PATH",
        str(db_path),
    )

    app = FastAPI()
    app.include_router(reconciliation_api.router)

    response = TestClient(app).get(
        "/autonomy/audit/reconciliation"
    )

    assert response.status_code == 200

    items = {
        item["run_id"]: item
        for item in response.json()["items"]
    }

    assert items["run-evidence-a"]["evidence"] == {
        "source": "a",
        "action_id": "action-a",
    }

    assert items["run-evidence-b"]["evidence"] == {
        "source": "b",
        "action_id": "action-b",
    }
