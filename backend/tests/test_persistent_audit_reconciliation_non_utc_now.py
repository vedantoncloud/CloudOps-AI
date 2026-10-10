from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_non_utc_now_is_normalized_to_utc(tmp_path, monkeypatch):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now_utc = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
    now_plus_five = timezone(timedelta(hours=5, minutes=30))
    supplied_now = now_utc.astimezone(now_plus_five)
    claimed_at = now_utc.timestamp() - 45

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [
                {
                    "run_id": "run-non-utc-now",
                    "event_type": "recovery_completed",
                    "claimed_at": claimed_at,
                    "evidence": {},
                }
            ]

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    result = PersistentAuditReconciliation(
        store, lease_seconds=300, now=supplied_now
    ).inspect()

    assert result.items[0].age_seconds == 45.0
    assert result.items[0].status == "active"
    assert result.active_count == 1
    assert result.stale_count == 0
