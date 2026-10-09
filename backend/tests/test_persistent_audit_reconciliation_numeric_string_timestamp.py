from __future__ import annotations

from datetime import datetime, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_numeric_string_claimed_at_is_parsed_as_timestamp(
    tmp_path, monkeypatch
):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
    claimed_at = now.timestamp() - 30

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [
                {
                    "run_id": "run-numeric-string",
                    "event_type": "recovery_completed",
                    "claimed_at": str(claimed_at),
                    "evidence": {},
                }
            ]

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    result = PersistentAuditReconciliation(
        store, lease_seconds=300, now=now
    ).inspect()

    assert result.items[0].claimed_at == claimed_at
    assert result.items[0].age_seconds == 30.0
    assert result.items[0].status == "active"
