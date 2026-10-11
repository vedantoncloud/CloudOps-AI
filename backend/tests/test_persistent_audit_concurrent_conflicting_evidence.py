from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_conflicting_evidence_preserves_single_record(tmp_path):
    database = tmp_path / "conflicting-audit.db"
    stores = [
        PersistentAuditIdempotencyStore(database)
        for _ in range(8)
    ]
    barrier = Barrier(8)

    evidence_items = [
        {"action_id": f"action-{index}", "outcome": "failed"}
        for index in range(8)
    ]

    def acquire(index):
        barrier.wait()
        try:
            claim = stores[index].claim(
                "conflicting-run",
                "recovery_failed",
                evidence_items[index],
            )
            return ("claimed", claim)
        except ValueError as error:
            return ("conflict", str(error))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(acquire, range(8)))

    successful = [
        result[1]
        for result in results
        if result[0] == "claimed" and result[1].emitted
    ]
    conflicts = [
        result
        for result in results
        if result[0] == "conflict"
    ]

    assert len(successful) == 1
    assert len(conflicts) == 7
    assert all("Conflicting audit evidence" in result[1] for result in conflicts)

    winner_evidence = successful[0].evidence

    repeated = stores[0].claim(
        "conflicting-run",
        "recovery_failed",
        winner_evidence,
    )

    assert repeated.emitted is False
    assert repeated.evidence == winner_evidence
