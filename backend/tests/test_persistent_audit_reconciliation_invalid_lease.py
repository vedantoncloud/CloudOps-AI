from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


@pytest.mark.parametrize("lease_seconds", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_lease_seconds_are_rejected(tmp_path, lease_seconds):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    with pytest.raises(
        ValueError, match="lease_seconds must be finite and non-negative"
    ):
        PersistentAuditReconciliation(
            store, lease_seconds=lease_seconds, now=now
        )
