from __future__ import annotations

import time

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_zero_lease_duration_is_clamped_to_one_second(
    tmp_path,
    monkeypatch,
):
    current_time = [3000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    store = PersistentAuditIdempotencyStore(
        tmp_path / "minimum-lease.db",
        lease_seconds=0,
    )

    assert store.lease_seconds == 1

    evidence = {"action_id": "minimum-lease"}

    first = store.claim(
        "minimum-lease-run",
        "recovery_completed",
        evidence,
    )

    assert first.emitted is True
    assert first.claim_token

    current_time[0] = 3000.999

    active = store.claim(
        "minimum-lease-run",
        "recovery_completed",
        evidence,
    )

    assert active.emitted is False
    assert active.claim_token == ""

    current_time[0] = 3001.0

    reclaimed = store.claim(
        "minimum-lease-run",
        "recovery_completed",
        evidence,
    )

    assert reclaimed.emitted is True
    assert reclaimed.claim_token
    assert reclaimed.claim_token != first.claim_token

    assert store.mark_emitted(
        "minimum-lease-run",
        "recovery_completed",
        first.claim_token,
    ) is False

    assert store.mark_emitted(
        "minimum-lease-run",
        "recovery_completed",
        reclaimed.claim_token,
    ) is True