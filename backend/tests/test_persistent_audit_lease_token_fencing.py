from __future__ import annotations

import time

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_expired_claim_rejects_old_token_and_accepts_reclaimed_token(
    tmp_path,
    monkeypatch,
):
    current_time = [1000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    store = PersistentAuditIdempotencyStore(
        tmp_path / "audit.db",
        lease_seconds=5,
    )

    evidence = {"action_id": "lease-fencing", "outcome": "completed"}

    first = store.claim("lease-run", "recovery_completed", evidence)

    assert first.emitted is True
    assert first.claim_token

    current_time[0] = 1002.0

    active = store.claim("lease-run", "recovery_completed", evidence)

    assert active.emitted is False
    assert active.claim_token == ""

    current_time[0] = 1006.0

    reclaimed = store.claim("lease-run", "recovery_completed", evidence)

    assert reclaimed.emitted is True
    assert reclaimed.claim_token
    assert reclaimed.claim_token != first.claim_token

    assert store.mark_emitted(
        "lease-run",
        "recovery_completed",
        first.claim_token,
    ) is False

    assert store.mark_emitted(
        "lease-run",
        "recovery_completed",
        reclaimed.claim_token,
    ) is True

    duplicate = store.claim("lease-run", "recovery_completed", evidence)

    assert duplicate.emitted is False
    assert duplicate.claim_token == ""