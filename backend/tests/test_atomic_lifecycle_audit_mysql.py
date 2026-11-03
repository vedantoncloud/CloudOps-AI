"""MySQL 8.4 tests for atomic lifecycle state and audit-chain commits."""

from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.action_models import ActionPlan, ActionTarget, RiskLevel
from autonomy.action_plan_store import ActionPlanStore
from autonomy.audit import AuditTrail
from autonomy.gitops import GitOpsChange, GitOpsChangeStatus, GitOpsEngine
from autonomy.gitops_registry import GitOpsChangeSetRegistry
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


def _plan(action_id):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-mysql-atomic",
            metadata={"region": "us-east-1"},
        ),
        reason="MySQL atomic transaction test.",
        risk=RiskLevel.MEDIUM,
    )


def _event(action_id, actor_id="operator-a"):
    return {
        "action_id": action_id,
        "action_type": "plan_created",
        "resource_type": "action_plan",
        "resource_id": action_id,
        "old_status": "none",
        "new_status": "proposed",
        "event": "plan_created",
        "actor_id": actor_id,
        "details": {"tenant_id": "tenant-mysql"},
    }


def _change_set(change_id):
    change_set = GitOpsEngine().create_change_set(
        source_action_id=f"action-{change_id}",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-mysql-atomic",
                field="instance_type",
                desired_value="t3.large",
                current_value="t3.medium",
                reason="MySQL atomic GitOps test.",
            )
        ],
    )
    change_set.change_id = change_id
    change_set.metadata["tenant_id"] = "tenant-mysql"
    return change_set


def _event_count(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT COUNT(*) FROM audit_events")).scalar_one()


def test_mysql_action_plan_and_audit_are_atomic(database_url):
    identity = f"mysql-plan-atomic-{uuid.uuid4().hex}"
    store = ActionPlanStore(database_url=database_url)
    trail = PersistentAuditTrail(database_url)
    try:
        store.save_many(
            [_plan(identity)],
            "tenant-mysql",
            audit_trail=trail,
            audit_events=[_event(identity)],
        )
        assert store.get(identity) is not None
        assert any(event.action_id == identity for event in trail.get_events())
        before_count = _event_count(store._engine)

        with pytest.raises(ValueError, match="actor_id cannot be empty"):
            store.save_many(
                [_plan(f"{identity}-rollback")],
                "tenant-mysql",
                audit_trail=trail,
                audit_events=[_event(f"{identity}-rollback", actor_id="")],
            )
        assert store.get(f"{identity}-rollback") is None
        assert _event_count(store._engine) == before_count
    finally:
        store.close()
        trail.close()


def test_mysql_gitops_registration_and_transition_are_atomic(database_url):
    identity = f"mysql-gitops-atomic-{uuid.uuid4().hex}"
    trail = PersistentAuditTrail(database_url)
    registry = GitOpsChangeSetRegistry(
        database_url=database_url,
        audit_trail=trail,
    )
    engine = create_engine(database_url, future=True)
    try:
        change_set = _change_set(identity)
        registry.register(change_set, actor_id="operator-a")
        assert registry.get(identity) is not None
        before_count = _event_count(engine)

        with pytest.raises(ValueError, match="actor_id cannot be empty"):
            registry.approve(identity, "operator-b", actor_id="")
        refreshed = registry.get(identity)
        assert refreshed.status == GitOpsChangeStatus.PENDING_APPROVAL
        assert _event_count(engine) == before_count

        registry.approve(identity, "operator-b", actor_id="operator-b")
        assert registry.get(identity).status == GitOpsChangeStatus.APPROVED
        assert _event_count(engine) == before_count + 1
        assert trail.verify_integrity()
    finally:
        engine.dispose()
        registry.close()
        trail.close()
