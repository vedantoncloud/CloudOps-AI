"""Shared SQLAlchemy audit-chain tests using a migrated SQLite schema."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.persistent_audit_trail import PersistentAuditTrail


@pytest.fixture
def shared_database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'shared-audit-chain.db'}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def _record(trail, index, tenant_id=None):
    return trail.record(
        action_id=f"action-{index}",
        action_type="test",
        resource_type="service",
        resource_id=f"resource-{index}",
        old_status="pending",
        new_status="completed",
        event="test_completed",
        details={"index": index, **({"tenant_id": tenant_id} if tenant_id else {})},
        actor_id="integration-test",
    )


def test_sqlalchemy_audit_chain_round_trips_and_exports(shared_database_url):
    trail = PersistentAuditTrail(shared_database_url)
    try:
        _record(trail, 1)
        _record(trail, 2)

        reopened = PersistentAuditTrail(shared_database_url)
        try:
            assert [event.action_id for event in reopened.get_events()] == [
                "action-1", "action-2"
            ]
            assert reopened.get_integrity_diagnostics().valid
            exported = reopened.get_verifiable_export()
            assert [item["sequence"] for item in exported["events"]] == [1, 2]
            assert exported["events"][1]["previous_hash"] == exported["events"][0]["event_hash"]
            assert exported["final_hash"] == exported["events"][-1]["event_hash"]
        finally:
            reopened.close()
    finally:
        trail.close()


def test_sqlalchemy_audit_chain_serializes_parallel_appends(shared_database_url):
    def append(index):
        trail = PersistentAuditTrail(shared_database_url)
        try:
            return _record(trail, index).action_id
        finally:
            trail.close()

    with ThreadPoolExecutor(max_workers=6) as executor:
        action_ids = list(executor.map(append, range(12)))

    trail = PersistentAuditTrail(shared_database_url)
    try:
        assert len(set(action_ids)) == 12
        assert len(trail.get_events()) == 12
        assert trail.get_integrity_diagnostics().valid
        exported = trail.get_verifiable_export()
        assert [item["sequence"] for item in exported["events"]] == list(range(1, 13))
        engine = create_engine(shared_database_url, future=True)
        try:
            with engine.connect() as connection:
                head = connection.execute(
                    text(
                        "SELECT last_sequence, last_hash FROM audit_chain_state "
                        "WHERE singleton_id = 1"
                    )
                ).one()
            assert head.last_sequence == 12
            assert head.last_hash == exported["final_hash"]
        finally:
            engine.dispose()
    finally:
        trail.close()


def test_sqlalchemy_audit_chain_fails_closed_when_head_metadata_is_inconsistent(
    shared_database_url,
):
    trail = PersistentAuditTrail(shared_database_url)
    try:
        _record(trail, 1)
        engine = create_engine(shared_database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE audit_chain_state SET last_hash = :bad "
                        "WHERE singleton_id = 1"
                    ),
                    {"bad": "0" * 64},
                )
        finally:
            engine.dispose()

        with pytest.raises(RuntimeError, match="head metadata is inconsistent"):
            _record(trail, 2)
        assert len(trail.get_events()) == 1
    finally:
        trail.close()


def test_sqlalchemy_audit_chain_clear_resets_the_locked_head(shared_database_url):
    trail = PersistentAuditTrail(shared_database_url)
    try:
        _record(trail, 1)
        trail.clear()
        _record(trail, 2)
        exported = trail.get_verifiable_export()
        assert [item["sequence"] for item in exported["events"]] == [1]
        assert trail.get_integrity_diagnostics().valid
    finally:
        trail.close()


def test_shared_audit_chain_requires_an_applied_schema(tmp_path):
    missing_url = f"sqlite:///{tmp_path / 'not-migrated.db'}"
    with pytest.raises(ValueError, match="run Alembic migrations first"):
        PersistentAuditTrail(missing_url)

def test_sqlalchemy_audit_chain_scopes_tenant_reads_in_repository(shared_database_url):
    trail = PersistentAuditTrail(shared_database_url)
    try:
        _record(trail, 1, tenant_id="tenant-a")
        _record(trail, 2, tenant_id="tenant-b")
        _record(trail, 3)

        tenant_a = trail.get_events(tenant_id="tenant-a", tenant_scoped=True)
        tenant_b = trail.get_events(tenant_id="tenant-b", tenant_scoped=True)
        assert [event.action_id for event in tenant_a] == ["action-1"]
        assert [event.action_id for event in tenant_b] == ["action-2"]

        engine = create_engine(shared_database_url, future=True)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT tenant_id FROM audit_events "
                        "WHERE tenant_id = :tenant_id ORDER BY sequence"
                    ),
                    {"tenant_id": "tenant-a"},
                ).all()
            assert [row.tenant_id for row in rows] == ["tenant-a"]
        finally:
            engine.dispose()
        assert trail.get_integrity_diagnostics().valid
    finally:
        trail.close()



def test_sqlalchemy_tenant_reads_fail_closed_without_tenant_identity(shared_database_url):
    trail = PersistentAuditTrail(shared_database_url)
    try:
        _record(trail, 1)
        assert trail.get_events(tenant_scoped=True) == []
    finally:
        trail.close()
