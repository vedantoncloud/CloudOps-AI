"""Shared idempotency claims and audit-chain events commit atomically."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.idempotent_failure_audit import IdempotentFailureAuditBridge
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_trail import PersistentAuditTrail


@pytest.fixture
def shared_database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'atomic-idempotent-audit.db'}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def _trace(run_id="run-atomic"):
    return AutonomousFailureTrace(
        run_id=run_id,
        outcome="failed",
        evidence={
            "run_id": run_id,
            "recovery_outcome": "failed",
            "recovery_evidence": {"action_id": f"action-{run_id}"},
            "trace": {"run_id": run_id, "action_id": f"action-{run_id}"},
        },
    )


def _claim_row(url, run_id, event_type):
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT status, claim_token FROM audit_idempotency "
                    "WHERE run_id = :run_id AND event_type = :event_type"
                ),
                {"run_id": run_id, "event_type": event_type},
            ).mappings().one()
    finally:
        engine.dispose()


def _expire_claim(url, run_id, event_type):
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE audit_idempotency SET claimed_at = 0 "
                    "WHERE run_id = :run_id AND event_type = :event_type"
                ),
                {"run_id": run_id, "event_type": event_type},
            )
    finally:
        engine.dispose()


def test_bridge_commits_event_and_claim_together_and_deduplicates(shared_database_url):
    store = PersistentAuditIdempotencyStore(database_url=shared_database_url)
    trail = PersistentAuditTrail(shared_database_url)
    bridge = IdempotentFailureAuditBridge(trail, store)
    try:
        first = bridge.record(_trace())
        second = bridge.record(_trace())

        assert first.emitted_events == ("autonomous_run_failed", "recovery_failed")
        assert second.emitted_events == ()
        assert len(trail.get_events()) == 2
        assert trail.verify_integrity()
        assert _claim_row(shared_database_url, "run-atomic", "autonomous_run_failed")["status"] == "emitted"
        assert _claim_row(shared_database_url, "run-atomic", "recovery_failed")["status"] == "emitted"
    finally:
        store.close()
        trail.close()


def test_audit_append_failure_rolls_back_claim_finalization_and_can_retry(
    shared_database_url, monkeypatch
):
    store = PersistentAuditIdempotencyStore(database_url=shared_database_url, lease_seconds=30)
    trail = PersistentAuditTrail(shared_database_url)
    bridge = IdempotentFailureAuditBridge(trail, store)
    original = trail.record_with_connection
    try:
        def fail_append(*args, **kwargs):
            raise OSError("audit append unavailable")

        monkeypatch.setattr(trail, "record_with_connection", fail_append)
        with pytest.raises(OSError, match="audit append unavailable"):
            bridge.record(_trace("run-retry"))

        row = _claim_row(shared_database_url, "run-retry", "autonomous_run_failed")
        assert row["status"] == "pending"
        assert trail.get_events() == []

        monkeypatch.setattr(trail, "record_with_connection", original)
        _expire_claim(shared_database_url, "run-retry", "autonomous_run_failed")
        result = bridge.record(_trace("run-retry"))

        assert result.emitted_events == ("autonomous_run_failed", "recovery_failed")
        assert len(trail.get_events()) == 2
        assert trail.verify_integrity()
    finally:
        store.close()
        trail.close()


def test_stale_claim_token_cannot_append_or_finalize_audit_event(shared_database_url):
    store = PersistentAuditIdempotencyStore(database_url=shared_database_url, lease_seconds=1)
    trail = PersistentAuditTrail(shared_database_url)
    run_id = "run-token-fence"
    event_type = "autonomous_run_failed"
    evidence = {"run_id": run_id, "outcome": "failed"}
    audit_kwargs = {
        "action_id": "action-token-fence",
        "action_type": "autonomous_failure_recovery",
        "resource_type": "autonomous_run",
        "resource_id": run_id,
        "old_status": "running",
        "new_status": "failed",
        "event": event_type,
        "details": evidence,
    }
    try:
        first = store.claim(run_id, event_type, evidence)
        _expire_claim(shared_database_url, run_id, event_type)
        second = store.claim(run_id, event_type, evidence)
        assert second.emitted and second.claim_token != first.claim_token

        assert store.mark_emitted_with_audit(
            run_id, event_type, first.claim_token, trail, audit_kwargs
        ) is False
        assert trail.get_events() == []

        assert store.mark_emitted_with_audit(
            run_id, event_type, second.claim_token, trail, audit_kwargs
        ) is True
        assert len(trail.get_events()) == 1
        assert _claim_row(shared_database_url, run_id, event_type)["status"] == "emitted"
        assert trail.verify_integrity()
    finally:
        store.close()
        trail.close()
