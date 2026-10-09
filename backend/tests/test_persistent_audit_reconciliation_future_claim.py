from __future__ import annotations

from datetime import datetime, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_future_claim_timestamp_has_zero_age_and_remains_active(
    tmp_path, monkeypatch
):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [
                {
                    "run_id": "run-future",
                    "event_type": "recovery_completed",
                    "claimed_at": now.timestamp() + 60,
                    "evidence": {"source": "test"},
                }
            ]

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    result = PersistentAuditReconciliation(
        store,
        lease_seconds=300,
        now=now,
    ).inspect()

    assert result.count == 1
    assert result.items[0].age_seconds == 0.0
    assert result.items[0].status == "active"
    assert result.active_count == 1
    assert result.stale_count == 0
