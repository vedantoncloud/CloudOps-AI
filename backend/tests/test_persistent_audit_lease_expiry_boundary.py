from __future__ import annotations

import time

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_claim_is_reclaimed_at_exact_lease_expiry_boundary(
    tmp_path,
    monkeypatch,
):
    current_time = [2000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    store = PersistentAuditIdempotencyStore(
        tmp_path / "audit.db",
        lease_seconds=5,
    )

    evidence = {"action_id": "boundary-check"}

    first = store.claim("boundary-run", "recovery_completed", evidence)

    assert first.emitted is True
    assert first.claim_token

    current_time[0] = 2004.999

    before_expiry = store.claim(
        "boundary-run",
        "recovery_completed",
        evidence,
    )

    assert before_expiry.emitted is False
    assert before_expiry.claim_token == ""

    current_time[0] = 2005.0

    at_expiry = store.claim(
        "boundary-run",
        "recovery_completed",
        evidence,
    )

    assert at_expiry.emitted is True
    assert at_expiry.claim_token
    assert at_expiry.claim_token != first.claim_token

    assert store.mark_emitted(
        "boundary-run",
        "recovery_completed",
        first.claim_token,
    ) is False

    assert store.mark_emitted(
        "boundary-run",
        "recovery_completed",
        at_expiry.claim_token,
    ) is True

    duplicate = store.claim(
        "boundary-run",
        "recovery_completed",
        evidence,
    )

    assert duplicate.emitted is False