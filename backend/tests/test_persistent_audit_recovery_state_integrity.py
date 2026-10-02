from __future__ import annotations

import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_pending_claim_survives_store_restart_and_finalizes_after_retry(tmp_path):
    path = tmp_path / "audit.db"
    evidence = {"action_id": "restart-recovery"}

    first_store = PersistentAuditIdempotencyStore(path)
    first_claim = first_store.claim(
        "restart-run",
        "recovery_completed",
        evidence,
    )

    assert first_claim.emitted is True
    assert first_claim.claim_token

    restarted_store = PersistentAuditIdempotencyStore(path)
    duplicate = restarted_store.claim(
        "restart-run",
        "recovery_completed",
        evidence,
    )

    assert duplicate.emitted is False
    assert duplicate.claim_token == ""

    pending_health = PersistentAuditHealthChecker(path).inspect()
    assert pending_health.total_claims == 1
    assert pending_health.pending_claims == 1
    assert pending_health.emitted_claims == 0
    assert pending_health.evidence["consistent"] is True

    assert restarted_store.mark_emitted(
        "restart-run",
        "recovery_completed",
        first_claim.claim_token,
    ) is True

    final_store = PersistentAuditIdempotencyStore(path)
    repeated = final_store.claim(
        "restart-run",
        "recovery_completed",
        evidence,
    )

    assert repeated.emitted is False
    assert repeated.claim_token == ""

    final_health = PersistentAuditHealthChecker(path).inspect()
    assert final_health.total_claims == 1
    assert final_health.pending_claims == 0
    assert final_health.emitted_claims == 1
    assert final_health.evidence["consistent"] is True


def test_reclaimed_lease_rejects_old_token_after_store_restart(tmp_path):
    path = tmp_path / "audit.db"
    evidence = {"action_id": "lease-restart"}

    original_store = PersistentAuditIdempotencyStore(
        path,
        lease_seconds=1,
    )
    original = original_store.claim(
        "lease-restart-run",
        "recovery_failed",
        evidence,
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = 0
            WHERE run_id = ? AND event_type = ?
            """,
            ("lease-restart-run", "recovery_failed"),
        )

    recovered_store = PersistentAuditIdempotencyStore(
        path,
        lease_seconds=1,
    )
    recovered = recovered_store.claim(
        "lease-restart-run",
        "recovery_failed",
        evidence,
    )

    assert recovered.emitted is True
    assert recovered.claim_token
    assert recovered.claim_token != original.claim_token

    assert recovered_store.mark_emitted(
        "lease-restart-run",
        "recovery_failed",
        original.claim_token,
    ) is False

    assert recovered_store.mark_emitted(
        "lease-restart-run",
        "recovery_failed",
        recovered.claim_token,
    ) is True

    health = PersistentAuditHealthChecker(path).inspect()
    assert health.total_claims == 1
    assert health.pending_claims == 0
    assert health.emitted_claims == 1
    assert health.evidence["consistent"] is True


def test_failed_finalization_can_be_retried_after_restart(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    claim = store.claim(
        "finalize-retry-run",
        "recovery_failed",
        {"action_id": "finalize-retry"},
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_emitted_update
            BEFORE UPDATE OF status ON audit_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'injected finalization failure');
            END
            """
        )

    try:
        store.mark_emitted(
            "finalize-retry-run",
            "recovery_failed",
            claim.claim_token,
        )
    except sqlite3.IntegrityError as exc:
        assert "injected finalization failure" in str(exc)
    else:
        raise AssertionError("Injected finalization failure was not raised")

    health_after_failure = PersistentAuditHealthChecker(path).inspect()
    assert health_after_failure.total_claims == 1
    assert health_after_failure.pending_claims == 1
    assert health_after_failure.emitted_claims == 0
    assert health_after_failure.evidence["consistent"] is True

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER reject_emitted_update")

    restarted_store = PersistentAuditIdempotencyStore(path)

    assert restarted_store.mark_emitted(
        "finalize-retry-run",
        "recovery_failed",
        claim.claim_token,
    ) is True

    final_health = PersistentAuditHealthChecker(path).inspect()
    assert final_health.total_claims == 1
    assert final_health.pending_claims == 0
    assert final_health.emitted_claims == 1
    assert final_health.evidence["consistent"] is True