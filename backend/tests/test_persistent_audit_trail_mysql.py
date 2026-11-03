"""MySQL 8.4 cross-worker append tests for the shared SHA-256 audit chain."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.persistent_audit_trail import PersistentAuditTrail


MYSQL_URL = os.environ.get("CLOUDOPS_MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="MySQL CI service is not configured")


@pytest.fixture(scope="module")
def database_url():
    assert MYSQL_URL
    os.environ["CLOUDOPS_DATABASE_URL"] = MYSQL_URL
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", MYSQL_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    yield MYSQL_URL


def _record(trail, identity, index):
    return trail.record(
        action_id=f"{identity}-{index}",
        action_type="integration_test",
        resource_type="service",
        resource_id=f"resource-{index}",
        old_status="pending",
        new_status="completed",
        event="integration_test_completed",
        details={"batch": identity, "index": index},
        actor_id="mysql-integration-test",
    )


def test_mysql_audit_chain_serializes_appends_from_independent_workers(database_url):
    identity = f"mysql-chain-{uuid.uuid4().hex}"

    def append(index):
        trail = PersistentAuditTrail(database_url)
        try:
            return _record(trail, identity, index).action_id
        finally:
            trail.close()

    with ThreadPoolExecutor(max_workers=10) as executor:
        action_ids = list(executor.map(append, range(20)))

    trail = PersistentAuditTrail(database_url)
    try:
        events = [event for event in trail.get_events() if event.action_id.startswith(identity)]
        assert len(set(action_ids)) == 20
        assert len(events) == 20
        assert trail.get_integrity_diagnostics().valid
        exported = trail.get_verifiable_export()
        selected = [
            item for item in exported["events"]
            if item["event"]["action_id"].startswith(identity)
        ]
        assert len(selected) == 20
        assert all(
            selected[index]["sequence"] < selected[index + 1]["sequence"]
            for index in range(len(selected) - 1)
        )
        assert all(
            selected[index + 1]["previous_hash"] == selected[index]["event_hash"]
            for index in range(len(selected) - 1)
        )
    finally:
        trail.close()


def test_mysql_audit_chain_rejects_stale_or_tampered_head_metadata(database_url):
    identity = f"mysql-chain-corrupt-{uuid.uuid4().hex}"
    trail = PersistentAuditTrail(database_url)
    try:
        _record(trail, identity, 1)
        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE audit_chain_state SET last_sequence = last_sequence + 10 "
                        "WHERE singleton_id = 1"
                    )
                )
        finally:
            engine.dispose()

        with pytest.raises(RuntimeError, match="head metadata is inconsistent"):
            _record(trail, identity, 2)

        # Restore the singleton head so this destructive integrity test cannot
        # poison other MySQL integration modules sharing the CI database.
        with engine.begin() as connection:
            tail = connection.execute(
                text(
                    "SELECT sequence, event_hash FROM audit_events "
                    "ORDER BY sequence DESC LIMIT 1"
                )
            ).mappings().first()
            connection.execute(
                text(
                    "UPDATE audit_chain_state SET last_sequence = :sequence, "
                    "last_hash = :event_hash WHERE singleton_id = 1"
                ),
                {
                    "sequence": int(tail["sequence"]) if tail else 0,
                    "event_hash": tail["event_hash"] if tail else "",
                },
            )
    finally:
        trail.close()
