import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_expired_claim_recovery_has_single_winner(tmp_path):
    database = tmp_path / "concurrent-reclaim.db"

    initial_store = PersistentAuditIdempotencyStore(
        database,
        lease_seconds=1,
    )

    original = initial_store.claim(
        "recovery-run",
        "recovery_failed",
        {"action_id": "action-1"},
    )

    assert original.emitted is True

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE audit_idempotency
            SET claimed_at = ?
            WHERE run_id = ? AND event_type = ?
            """,
            (time.time() - 10, "recovery-run", "recovery_failed"),
        )

    stores = [
        PersistentAuditIdempotencyStore(database, lease_seconds=1)
        for _ in range(8)
    ]
    barrier = Barrier(8)

    def reclaim(store):
        barrier.wait()
        return store.claim(
            "recovery-run",
            "recovery_failed",
            {"action_id": "action-1"},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(reclaim, stores))

    winners = [claim for claim in results if claim.emitted]
    pending = [claim for claim in results if not claim.emitted]

    assert len(winners) == 1
    assert len(pending) == 7

    winner = winners[0]
    assert winner.claim_token
    assert winner.claim_token != original.claim_token
    assert all(not claim.claim_token for claim in pending)

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT status, claim_token, claimed_at
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            ("recovery-run", "recovery_failed"),
        ).fetchone()

    assert row[0] == "pending"
    assert row[1] == winner.claim_token
    assert row[2] > time.time() - 5

    repeated = stores[0].claim(
        "recovery-run",
        "recovery_failed",
        {"action_id": "action-1"},
    )

    assert repeated.emitted is False
    assert repeated.claim_token == ""
    assert repeated.evidence == {"action_id": "action-1"}
