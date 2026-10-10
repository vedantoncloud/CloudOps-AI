from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_future_claim_with_zero_lease_is_stale(tmp_path, monkeypatch):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
    claimed_at = now + timedelta(seconds=60)

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [
                {
                    "run_id": "run-future-zero-lease",
                    "event_type": "recovery_completed",
                    "claimed_at": claimed_at.timestamp(),
                    "evidence": {},
                }
            ]

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    result = PersistentAuditReconciliation(
        store, lease_seconds=0, now=now
    ).inspect()

    assert result.items[0].age_seconds == 0.0
    assert result.items[0].status == "stale"
    assert result.stale_count == 1
    assert result.active_count == 0
