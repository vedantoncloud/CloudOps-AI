from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_finalization_succeeds_for_exactly_one_worker(tmp_path):
    database = tmp_path / "concurrent-finalization.db"
    evidence = {"action_id": "finalize-1", "outcome": "failed"}

    stores = [
        PersistentAuditIdempotencyStore(database)
        for _ in range(8)
    ]

    initial_claim = stores[0].claim(
        "concurrent-finalize-run",
        "recovery_failed",
        evidence,
    )

    assert initial_claim.emitted is True
    assert initial_claim.claim_token

    barrier = Barrier(8)

    def finalize(store):
        barrier.wait()
        return store.mark_emitted(
            "concurrent-finalize-run",
            "recovery_failed",
            initial_claim.claim_token,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(finalize, stores))

    assert results.count(True) == 1
    assert results.count(False) == 7

    repeated_claim = stores[0].claim(
        "concurrent-finalize-run",
        "recovery_failed",
        evidence,
    )

    assert repeated_claim.emitted is False
    assert repeated_claim.claim_token == ""
