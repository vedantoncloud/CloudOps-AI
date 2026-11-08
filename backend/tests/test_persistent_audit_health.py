from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_health import PersistentAuditHealthChecker


def test_health_counts_pending_and_emitted(tmp_path: Path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    pending = store.claim(
        "run-1",
        "recovery_failed",
        {"action_id": "a-1"},
    )
    emitted = store.claim(
        "run-2",
        "recovery_completed",
        {"action_id": "a-2"},
    )
    assert store.mark_emitted(
        "run-2",
        "recovery_completed",
        emitted.claim_token,
    )

    health = PersistentAuditHealthChecker(path).inspect()

    assert health.total_claims == 2
    assert health.pending_claims == 1
    assert health.emitted_claims == 1
    assert health.evidence["read_only"] is True
    assert health.evidence["consistent"] is True


def test_pending_claims_are_listed_deterministically(tmp_path: Path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    store.claim("run-b", "recovery_failed", {"action_id": "b"})
    store.claim("run-a", "recovery_failed", {"action_id": "a"})

    pending = PersistentAuditHealthChecker(path).list_pending()

    assert [item["run_id"] for item in pending] == ["run-a", "run-b"]
    assert pending[0]["event_type"] == "recovery_failed"
    assert pending[0]["evidence"]["action_id"] == "a"


def test_health_does_not_mutate_store(tmp_path: Path):
    path = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(path)

    claim = store.claim("run-1", "recovery_failed", {"action_id": "a-1"})

    checker = PersistentAuditHealthChecker(path)
    before = checker.inspect()
    checker.list_pending()
    after = checker.inspect()

    assert before == after
    assert claim.claim_token
    assert before.pending_claims == 1


def test_missing_store_is_reported(tmp_path: Path):
    with pytest.raises(
        ValueError,
        match="not initialized",
    ):
        PersistentAuditHealthChecker(tmp_path / "missing.db").inspect()


def test_health_reports_empty_initialized_store(tmp_path: Path):
    path = tmp_path / "audit.db"
    PersistentAuditIdempotencyStore(path)

    health = PersistentAuditHealthChecker(path).inspect()

    assert health.total_claims == 0
    assert health.pending_claims == 0
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is True


def test_shared_sql_health_marks_malformed_evidence_inconsistent(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'shared-audit.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE audit_idempotency (
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    evidence_json TEXT,
                    status TEXT NOT NULL,
                    claim_token TEXT NOT NULL,
                    claimed_at REAL NOT NULL,
                    PRIMARY KEY (run_id, event_type)
                )
            """))
            connection.execute(text("""
                INSERT INTO audit_idempotency
                    (run_id, event_type, evidence_json, status, claim_token, claimed_at)
                VALUES ('run-malformed', 'recovery_failed', 'not-json', 'pending', 'token', 1)
            """))
    finally:
        engine.dispose()

    health = PersistentAuditHealthChecker(database_url).inspect()

    assert health.evidence["malformed_evidence_claims"] == 1
    assert health.evidence["consistent"] is False
