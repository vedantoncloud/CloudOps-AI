"""MySQL 8.4 atomic idempotency and audit-chain integration tests."""

from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.autonomous_failure_trace import AutonomousFailureTrace
from autonomy.idempotent_failure_audit import IdempotentFailureAuditBridge
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_trail import PersistentAuditTrail


MYSQL_URL = os.environ.get("CLOUDOPS_MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="MySQL CI service is not configured")


@pytest.fixture(scope="module")
def database_url():
    assert MYSQL_URL
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", MYSQL_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    yield MYSQL_URL


def _trace(run_id):
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


def _status(database_url, run_id, event_type):
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT status FROM audit_idempotency "
                    "WHERE run_id = :run_id AND event_type = :event_type"
                ),
                {"run_id": run_id, "event_type": event_type},
            ).scalar_one()
    finally:
        engine.dispose()


def test_mysql_bridge_commits_audit_events_and_claim_finalization_atomically(database_url):
    run_id = f"mysql-atomic-{uuid.uuid4().hex}"
    store = PersistentAuditIdempotencyStore(database_url=database_url)
    trail = PersistentAuditTrail(database_url)
    bridge = IdempotentFailureAuditBridge(trail, store)
    try:
        first = bridge.record(_trace(run_id))
        second = bridge.record(_trace(run_id))

        assert first.emitted_events == ("autonomous_run_failed", "recovery_failed")
        assert second.emitted_events == ()
        assert _status(database_url, run_id, "autonomous_run_failed") == "emitted"
        assert _status(database_url, run_id, "recovery_failed") == "emitted"
        events = [event for event in trail.get_events() if event.details.get("run_id") == run_id]
        assert sorted(event.event for event in events) == [
            "autonomous_run_failed",
            "recovery_failed",
        ]
        recovery_events = [
            event for event in trail.get_events()
            if event.details.get("run_id") == run_id and event.event == "recovery_failed"
        ]
        assert len(recovery_events) == 1
        assert trail.verify_integrity()
    finally:
        store.close()
        trail.close()


def test_mysql_audit_failure_rolls_back_idempotency_finalization(database_url, monkeypatch):
    run_id = f"mysql-rollback-{uuid.uuid4().hex}"
    store = PersistentAuditIdempotencyStore(database_url=database_url)
    trail = PersistentAuditTrail(database_url)
    bridge = IdempotentFailureAuditBridge(trail, store)
    original = trail.record_with_connection
    try:
        monkeypatch.setattr(
            trail,
            "record_with_connection",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("audit unavailable")),
        )
        with pytest.raises(OSError, match="audit unavailable"):
            bridge.record(_trace(run_id))

        assert _status(database_url, run_id, "autonomous_run_failed") == "pending"
        assert not any(event.details.get("run_id") == run_id for event in trail.get_events())

        monkeypatch.setattr(trail, "record_with_connection", original)
        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE audit_idempotency SET claimed_at = 0 "
                        "WHERE run_id = :run_id AND event_type = 'autonomous_run_failed'"
                    ),
                    {"run_id": run_id},
                )
        finally:
            engine.dispose()

        result = bridge.record(_trace(run_id))
        assert result.emitted_events == ("autonomous_run_failed", "recovery_failed")
        assert _status(database_url, run_id, "autonomous_run_failed") == "emitted"
        assert trail.verify_integrity()
    finally:
        store.close()
        trail.close()
