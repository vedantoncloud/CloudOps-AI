from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_duplicate_claims_create_one_active_claim(tmp_path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    worker_count = 8
    barrier = Barrier(worker_count)

    def attempt_claim(_):
        store = PersistentAuditIdempotencyStore(path)
        barrier.wait(timeout=10)
        return store.claim(
            "run-concurrent",
            "recovery_failed",
            {"action_id": "shared-action"},
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(attempt_claim, range(worker_count)))

    active = [result for result in results if result.emitted]

    assert len(active) == 1
    assert active[0].claim_token

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT claim_token)
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            ("run-concurrent", "recovery_failed"),
        ).fetchone()

    assert rows == (1, 1)


def test_concurrent_distinct_events_remain_independent(tmp_path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    events = [
        "recovery_failed",
        "recovery_completed",
        "autonomous_run_failed",
        "autonomous_run_completed",
    ]

    def claim_event(event_type):
        store = PersistentAuditIdempotencyStore(path)
        return store.claim(
            "run-multiple-events",
            event_type,
            {"event": event_type},
        )

    with ThreadPoolExecutor(max_workers=len(events)) as executor:
        results = list(executor.map(claim_event, events))

    assert all(result.emitted for result in results)
    assert len({result.event_type for result in results}) == len(events)

    with sqlite3.connect(path) as connection:
        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM audit_idempotency
            WHERE run_id = ?
            """,
            ("run-multiple-events",),
        ).fetchone()[0]

    assert count == len(events)


def test_concurrent_claims_leave_consistent_health_counts(tmp_path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    worker_count = 6
    barrier = Barrier(worker_count)

    def attempt_claim(index):
        store = PersistentAuditIdempotencyStore(path)
        barrier.wait(timeout=10)
        return store.claim(
            f"run-{index}",
            "recovery_failed",
            {"index": index},
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(attempt_claim, range(worker_count)))

    assert all(result.emitted for result in results)

    health = PersistentAuditHealthChecker(path).inspect()

    assert health.total_claims == worker_count
    assert health.pending_claims == worker_count
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is True
