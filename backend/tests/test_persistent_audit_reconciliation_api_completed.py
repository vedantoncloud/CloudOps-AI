from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import autonomy.persistent_audit_reconciliation_api as reconciliation_api
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_reconciliation_api_ignores_emitted_claims(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(db_path)

    claim = store.claim(
        run_id="run-emitted",
        event_type="recovery_completed",
        evidence={"source": "emitted"},
    )

    assert claim.emitted is True
    assert claim.claim_token

    assert store.mark_emitted(
        "run-emitted",
        "recovery_completed",
        claim.claim_token,
    ) is True

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

    body = response.json()

    assert body["count"] == 0
    assert body["active_count"] == 0
    assert body["stale_count"] == 0
    assert body["items"] == []
    assert body["evidence"]["pending_count"] == 0

    assert store.contains(
        "run-emitted",
        "recovery_completed",
    ) is True
