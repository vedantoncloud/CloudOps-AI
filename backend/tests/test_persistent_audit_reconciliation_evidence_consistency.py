from __future__ import annotations

from datetime import datetime, timezone

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def test_reconciliation_evidence_counts_match_item_statuses(tmp_path, monkeypatch):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    store.claim(
        "run-active",
        "recovery_completed",
        {"source": "consistency-test", "run_id": "run-active"},
    )
    store.claim(
        "run-stale",
        "recovery_failed",
        {"source": "consistency-test", "run_id": "run-stale"},
    )

    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    pending = [
        {
            "run_id": "run-active",
            "event_type": "recovery_completed",
            "claimed_at": now.timestamp() - 10,
            "evidence": {
                "source": "consistency-test",
                "run_id": "run-active",
            },
        },
        {
            "run_id": "run-stale",
            "event_type": "recovery_failed",
            "claimed_at": now.timestamp() - 301,
            "evidence": {
                "source": "consistency-test",
                "run_id": "run-stale",
            },
        },
    ]

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return pending

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    result = PersistentAuditReconciliation(
        store,
        lease_seconds=300,
        now=now,
    ).inspect()

    active_items = [
        item for item in result.items if item.status == "active"
    ]
    stale_items = [
        item for item in result.items if item.status == "stale"
    ]

    assert result.count == len(result.items) == 2
    assert result.active_count == len(active_items) == 1
    assert result.stale_count == len(stale_items) == 1

    assert result.evidence["pending_count"] == result.count
    assert result.evidence["active_count"] == result.active_count
    assert result.evidence["stale_count"] == result.stale_count
    assert result.evidence["read_only"] is True
