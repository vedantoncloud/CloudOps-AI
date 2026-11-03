"""MySQL 8.4 cross-worker GitOps registry integration tests."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.gitops import GitOpsChange, GitOpsChangeStatus, GitOpsEngine
from autonomy.gitops_registry import GitOpsChangeSetRegistry


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


def _change_set(change_id):
    change_set = GitOpsEngine().create_change_set(
        source_action_id=f"action-{change_id}",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-mysql-gitops",
                field="instance_type",
                desired_value="t3.large",
                current_value="t3.medium",
                reason="MySQL cross-worker registry test",
            )
        ],
    )
    change_set.change_id = change_id
    change_set.metadata["tenant_id"] = "tenant-mysql"
    return change_set


def test_mysql_registry_refreshes_changes_across_instances(database_url):
    identity = f"mysql-gitops-{uuid.uuid4().hex}"
    first = GitOpsChangeSetRegistry(database_url=database_url)
    second = GitOpsChangeSetRegistry(database_url=database_url)
    try:
        first.register(_change_set(identity))
        assert second.get(identity).metadata["tenant_id"] == "tenant-mysql"
        second.approve(identity, "operator-mysql")
        refreshed = first.get(identity)
        assert refreshed.status == GitOpsChangeStatus.APPROVED
        assert refreshed.approved_by == "operator-mysql"
    finally:
        first.close()
        second.close()


def test_mysql_registry_fences_stale_worker_transitions(database_url):
    identity = f"mysql-gitops-cas-{uuid.uuid4().hex}"
    first = GitOpsChangeSetRegistry(database_url=database_url)
    second = GitOpsChangeSetRegistry(database_url=database_url)
    try:
        first.register(_change_set(identity))
        stale = first.get(identity)
        previous = copy.deepcopy(stale)
        second.approve(identity, "operator-current")
        GitOpsEngine().approve(stale, "operator-stale")
        with pytest.raises(ValueError, match="modified by another worker"):
            first._persist_change(stale, previous)
        current = first.get(identity)
        assert current.status == GitOpsChangeStatus.APPROVED
        assert current.approved_by == "operator-current"
    finally:
        first.close()
        second.close()


def test_mysql_registry_serializes_concurrent_registrations(database_url):
    identity = f"mysql-gitops-order-{uuid.uuid4().hex}"

    def register(index):
        registry = GitOpsChangeSetRegistry(database_url=database_url)
        try:
            registry.register(_change_set(f"{identity}-{index:02d}"))
        finally:
            registry.close()

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(register, range(20)))

    engine = create_engine(database_url, future=True)
    registry = GitOpsChangeSetRegistry(database_url=database_url)
    try:
        rows = engine.connect().execute(
            text(
                "SELECT change_id, tenant_id, created_order FROM gitops_change_sets "
                "WHERE change_id LIKE :prefix ORDER BY created_order"
            ),
            {"prefix": f"{identity}-%"},
        ).all()
        assert len(rows) == 20
        orders = [row.created_order for row in rows]
        assert len(set(orders)) == 20
        assert orders == sorted(orders)
        assert all(row.tenant_id == "tenant-mysql" for row in rows)
        assert len([item for item in registry.list_all() if item.change_id.startswith(identity)]) == 20
    finally:
        engine.dispose()
        registry.close()
