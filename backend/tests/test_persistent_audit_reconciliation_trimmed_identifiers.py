from datetime import datetime, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_pending_claim_identifiers_are_trimmed(tmp_path, monkeypatch):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [{
                "run_id": "  run-123  ",
                "event_type": "  recovery_completed  ",
                "claimed_at": now.timestamp() - 30,
                "evidence": {},
            }]

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    result = PersistentAuditReconciliation(
        store, now=now, lease_seconds=300
    ).inspect()

    assert result.count == 1
    assert result.items[0].run_id == "run-123"
    assert result.items[0].event_type == "recovery_completed"
    assert result.items[0].age_seconds == 30.0
    assert result.items[0].status == "active"
