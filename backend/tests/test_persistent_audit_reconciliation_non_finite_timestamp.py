from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


@pytest.mark.parametrize("claimed_at", ["nan", "inf", "-inf"])
def test_non_finite_claimed_at_timestamp_is_rejected(
    tmp_path, monkeypatch, claimed_at
):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [
                {
                    "run_id": "run-non-finite-timestamp",
                    "event_type": "recovery_completed",
                    "claimed_at": claimed_at,
                    "evidence": {},
                }
            ]

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )

    reconciliation = PersistentAuditReconciliation(
        store, lease_seconds=300, now=now
    )

    with pytest.raises(ValueError, match="invalid claimed_at timestamp"):
        reconciliation.inspect()
