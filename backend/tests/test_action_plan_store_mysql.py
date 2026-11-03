"""MySQL 8.4 multi-worker action-plan ordering integration tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.action_models import ActionPlan, ActionTarget, RiskLevel
from autonomy.action_plan_store import ActionPlanStore


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


def _plan(action_id):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-mysql-plan",
            metadata={"region": "us-east-1"},
        ),
        reason="Concurrent MySQL action-plan persistence test.",
        risk=RiskLevel.MEDIUM,
    )


def test_mysql_allocator_serializes_concurrent_plan_creates(database_url):
    identity = f"mysql-plan-{uuid.uuid4().hex}"

    def save(index):
        store = ActionPlanStore(database_url=database_url)
        try:
            store.save_many([_plan(f"{identity}-{index}")], "tenant-mysql")
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(save, range(20)))

    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT action_id, tenant_id, created_order FROM action_plans "
                    "WHERE action_id LIKE :prefix ORDER BY created_order"
                ),
                {"prefix": f"{identity}-%"},
            ).all()
        orders = [row.created_order for row in rows]
        assert len(rows) == 20
        assert len(set(orders)) == 20
        assert orders == sorted(orders)
        assert all(row.tenant_id == "tenant-mysql" for row in rows)
    finally:
        engine.dispose()


def test_mysql_updates_preserve_creation_order_and_tenant_metadata(database_url):
    identity = f"mysql-plan-update-{uuid.uuid4().hex}"
    store = ActionPlanStore(database_url=database_url)
    try:
        store.save_many([_plan(identity)], "tenant-before")
        engine = create_engine(database_url, future=True)
        try:
            with engine.connect() as connection:
                before = connection.execute(
                    text(
                        "SELECT created_order FROM action_plans WHERE action_id = :id"
                    ),
                    {"id": identity},
                ).scalar_one()
        finally:
            engine.dispose()

        updated = _plan(identity)
        updated.reason = "Updated action-plan content."
        store.save_many([updated], "tenant-after")

        restored, tenant = store.get(identity)
        assert restored.reason == "Updated action-plan content."
        assert tenant == "tenant-after"
        engine = create_engine(database_url, future=True)
        try:
            with engine.connect() as connection:
                after = connection.execute(
                    text(
                        "SELECT created_order FROM action_plans WHERE action_id = :id"
                    ),
                    {"id": identity},
                ).scalar_one()
            assert after == before
        finally:
            engine.dispose()
    finally:
        store.close()
