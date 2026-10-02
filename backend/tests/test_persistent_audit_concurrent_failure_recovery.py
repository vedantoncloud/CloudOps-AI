from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_workers_recover_after_insert_failure(tmp_path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_one_insert
            BEFORE INSERT ON audit_idempotency
            WHEN NEW.run_id = 'recover-run'
            BEGIN
                SELECT RAISE(ABORT, 'injected concurrent failure');
            END
            """
        )

    worker_count = 6
    barrier = Barrier(worker_count)

    def attempt(_):
        store = PersistentAuditIdempotencyStore(path)
        barrier.wait(timeout=10)
        try:
            return store.claim(
                "recover-run",
                "recovery_failed",
                {"action_id": "shared"},
            )
        except sqlite3.IntegrityError:
            return "failed"

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(attempt, range(worker_count)))

    assert results == ["failed"] * worker_count

    with sqlite3.connect(path) as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) FROM audit_idempotency
            WHERE run_id = 'recover-run'
            """
        ).fetchone()[0]

    assert count == 0

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER reject_one_insert")

    retry_store = PersistentAuditIdempotencyStore(path)
    retry = retry_store.claim(
        "recover-run",
        "recovery_failed",
        {"action_id": "shared"},
    )

    assert retry.emitted is True
    assert retry.claim_token


def test_concurrent_retry_creates_only_one_active_claim(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    worker_count = 8
    barrier = Barrier(worker_count)

    def attempt(_):
        worker_store = PersistentAuditIdempotencyStore(path)
        barrier.wait(timeout=10)
        return worker_store.claim(
            "retry-race",
            "recovery_completed",
            {"action_id": "same"},
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(attempt, range(worker_count)))

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
            ("retry-race", "recovery_completed"),
        ).fetchone()

    assert rows == (1, 1)


def test_health_counts_remain_consistent_after_recovery(tmp_path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    claim = store.claim(
        "health-recovery",
        "recovery_failed",
        {"action_id": "health"},
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_emitted_update
            BEFORE UPDATE OF status ON audit_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'injected status failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        store.mark_emitted(
            "health-recovery",
            "recovery_failed",
            claim.claim_token,
        )

    health = PersistentAuditHealthChecker(path).inspect()

    assert health.total_claims == 1
    assert health.pending_claims == 1
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is True
