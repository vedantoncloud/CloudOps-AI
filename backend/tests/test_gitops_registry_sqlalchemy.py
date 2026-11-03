"""Shared SQLAlchemy GitOps registry tests using a migrated SQLite schema."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.gitops import GitOpsChange, GitOpsChangeStatus, GitOpsEngine
from autonomy.gitops_registry import GitOpsChangeSetRegistry


@pytest.fixture
def shared_database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'shared-gitops.db'}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def _change_set(change_id):
    change_set = GitOpsEngine().create_change_set(
        source_action_id=f"action-{change_id}",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-123456789",
                field="instance_type",
                desired_value="t3.large",
                current_value="t3.medium",
                reason="Shared registry integration test",
            )
        ],
    )
    change_set.change_id = change_id
    change_set.metadata["tenant_id"] = "tenant-a"
    return change_set


def test_shared_registry_refreshes_other_workers_and_tenant_metadata(shared_database_url):
    first = GitOpsChangeSetRegistry(database_url=shared_database_url)
    second = GitOpsChangeSetRegistry(database_url=shared_database_url)
    change_set = _change_set("change-shared")
    try:
        first.register(change_set)
        loaded = second.get(change_set.change_id)
        assert loaded is not None
        assert loaded.metadata["tenant_id"] == "tenant-a"
        assert second.list_all()[0].change_id == change_set.change_id

        first.approve(change_set.change_id, "operator-a")
        refreshed = second.get(change_set.change_id)
        assert refreshed is not None
        assert refreshed.status == GitOpsChangeStatus.APPROVED
        assert refreshed.approved_by == "operator-a"
    finally:
        first.close()
        second.close()


def test_shared_registry_rejects_stale_cross_worker_transitions(shared_database_url):
    first = GitOpsChangeSetRegistry(database_url=shared_database_url)
    second = GitOpsChangeSetRegistry(database_url=shared_database_url)
    change_set = _change_set("change-cas")
    try:
        first.register(change_set)
        stale = first.get(change_set.change_id)
        assert stale is not None
        previous = copy.deepcopy(stale)

        second.approve(change_set.change_id, "operator-b")
        GitOpsEngine().approve(stale, "operator-stale")
        with pytest.raises(ValueError, match="modified by another worker"):
            first._persist_change(stale, previous)

        current = first.get(change_set.change_id)
        assert current is not None
        assert current.status == GitOpsChangeStatus.APPROVED
        assert current.approved_by == "operator-b"
    finally:
        first.close()
        second.close()


def test_shared_registry_serializes_concurrent_registration_and_order(shared_database_url):
    def register(index):
        registry = GitOpsChangeSetRegistry(database_url=shared_database_url)
        try:
            registry.register(_change_set(f"change-{index:02d}"))
        finally:
            registry.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(register, range(16)))

    registry = GitOpsChangeSetRegistry(database_url=shared_database_url)
    engine = create_engine(shared_database_url, future=True)
    try:
        changes = registry.list_all()
        assert len(changes) == 16
        assert {item.change_id for item in changes} == {
            f"change-{index:02d}" for index in range(16)
        }
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT change_id, tenant_id, created_order "
                    "FROM gitops_change_sets ORDER BY created_order"
                )
            ).all()
            state = connection.execute(
                text("SELECT last_created_order FROM gitops_state WHERE singleton_id = 1")
            ).scalar_one()
        assert [row.created_order for row in rows] == list(range(1, 17))
        assert all(row.tenant_id == "tenant-a" for row in rows)
        assert state == 16
        assert [item.change_id for item in changes] == [row.change_id for row in rows]
    finally:
        engine.dispose()
        registry.close()


def test_shared_registry_observes_remote_clear_and_re_registration(shared_database_url):
    first = GitOpsChangeSetRegistry(database_url=shared_database_url)
    second = GitOpsChangeSetRegistry(database_url=shared_database_url)
    change_set = _change_set("change-clear")
    try:
        first.register(change_set)
        second.get(change_set.change_id)
        first.clear()
        assert second.get(change_set.change_id) is None
        second.register(_change_set(change_set.change_id))
        assert first.get(change_set.change_id) is not None
    finally:
        first.close()
        second.close()


def test_shared_registry_requires_an_applied_schema(tmp_path):
    missing_url = f"sqlite:///{tmp_path / 'not-migrated.db'}"
    with pytest.raises(ValueError, match="run Alembic migrations first"):
        GitOpsChangeSetRegistry(database_url=missing_url)


def test_shared_registry_fails_closed_on_tenant_column_payload_mismatch(shared_database_url):
    registry = GitOpsChangeSetRegistry(database_url=shared_database_url)
    change_set = _change_set("change-tenant-mismatch")
    registry.register(change_set)
    engine = create_engine(shared_database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE gitops_change_sets SET tenant_id = 'tenant-b' "
                    "WHERE change_id = 'change-tenant-mismatch'"
                )
            )
        with pytest.raises(ValueError, match="tenant ownership metadata is inconsistent"):
            registry.get(change_set.change_id)
    finally:
        engine.dispose()
        registry.close()


def test_shared_registry_checks_tenant_inside_transition(shared_database_url):
    registry = GitOpsChangeSetRegistry(database_url=shared_database_url)
    change_set = _change_set("change-tenant-transition")
    try:
        registry.register(change_set)
        with pytest.raises(KeyError, match="GitOps change set not found"):
            registry.approve(
                change_set.change_id,
                "operator-b",
                tenant_id="tenant-b",
                tenant_scoped=True,
            )
        assert registry.get(change_set.change_id).status == GitOpsChangeStatus.PENDING_APPROVAL
    finally:
        registry.close()
