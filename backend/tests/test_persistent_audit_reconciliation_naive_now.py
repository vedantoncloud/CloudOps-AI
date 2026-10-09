from __future__ import annotations

from datetime import datetime, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_naive_now_is_interpreted_as_utc(tmp_path, monkeypatch):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0)

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [
                {
                    "run_id": "run-utc",
                    "event_type": "recovery_completed",
                    "claimed_at": datetime(
                        2026, 9, 28, 19, 55, tzinfo=timezone.utc
                    ).timestamp(),
                    "evidence": {},
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

    assert result.items[0].age_seconds == 300.0
    assert result.items[0].status == "stale"
    assert result.stale_count == 1
    assert result.active_count == 0
