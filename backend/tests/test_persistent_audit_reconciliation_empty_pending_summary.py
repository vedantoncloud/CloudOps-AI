from datetime import datetime, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_empty_pending_summary_with_zero_lease(tmp_path, monkeypatch):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return []

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    result = PersistentAuditReconciliation(
        store,
        lease_seconds=0,
        now=datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc),
    ).inspect()

    assert result.items == ()
    assert result.count == 0
    assert result.active_count == 0
    assert result.stale_count == 0
    assert result.evidence == {
        "store": "sqlite",
        "read_only": True,
        "lease_seconds": 0.0,
        "pending_count": 0,
        "active_count": 0,
        "stale_count": 0,
    }
