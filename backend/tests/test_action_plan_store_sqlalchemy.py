"""Shared SQLAlchemy action-plan persistence tests using a migrated SQLite schema."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.action_plan_store import ActionPlanStore


@pytest.fixture
def shared_database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'shared-action-plans.db'}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def _plan(action_id="plan-1"):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id=f"i-{action_id}",
            metadata={"region": "us-east-1"},
        ),
        reason="Review the instance state.",
        risk=RiskLevel.MEDIUM,
    )


def test_sqlalchemy_store_round_trips_tenant_and_preserves_update_order(shared_database_url):
    store = ActionPlanStore(database_url=shared_database_url)
    try:
        first, second = _plan("first"), _plan("second")
        store.save_many([first, second], "tenant-a")
        first.status = ActionStatus.REJECTED
        store.save_many([first], "tenant-b")

        restored, tenant = store.get("first")
        assert restored == first
        assert tenant == "tenant-b"
        assert [plan.action_id for plan, _ in store.load_all()] == ["first", "second"]
    finally:
        store.close()


def test_sqlalchemy_save_many_rolls_back_all_plans_on_encoding_failure(shared_database_url):
    store = ActionPlanStore(database_url=shared_database_url)
    invalid = _plan("invalid")
    invalid.target.metadata["bad"] = object()
    try:
        with pytest.raises(TypeError):
            store.save_many([_plan("valid"), invalid], "tenant-a")
        assert store.load_all() == []
    finally:
        store.close()


def test_sqlalchemy_allocator_serializes_concurrent_creates(shared_database_url):
    def save(index):
        store = ActionPlanStore(database_url=shared_database_url)
        try:
            store.save_many([_plan(f"concurrent-{index}")], "tenant-shared")
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(save, range(16)))

    store = ActionPlanStore(database_url=shared_database_url)
    try:
        plans = store.load_all()
        assert len(plans) == 16
        assert [plan.action_id for plan, _ in plans] == [
            f"concurrent-{index}" for index in range(16)
        ]
        assert all(tenant == "tenant-shared" for _, tenant in plans)
    finally:
        store.close()


def test_shared_action_plan_store_requires_migrations(tmp_path):
    missing_url = f"sqlite:///{tmp_path / 'not-migrated.db'}"
    with pytest.raises(ValueError, match="run Alembic migrations first"):
        ActionPlanStore(database_url=missing_url)
