"""Shared state and audit-chain writes must commit or roll back together."""

from __future__ import annotations

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


@pytest.fixture
def shared_database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'atomic-lifecycle-audit.db'}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def _plan(action_id="plan-atomic"):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-atomic",
            metadata={"region": "us-east-1"},
        ),
        reason="Atomic persistence integration test.",
        risk=RiskLevel.MEDIUM,
    )


def _audit_event(action_id, *, actor_id="operator-a"):
    return {
        "action_id": action_id,
        "action_type": "plan_created",
        "resource_type": "action_plan",
        "resource_id": action_id,
        "old_status": "none",
        "new_status": "proposed",
        "event": "plan_created",
        "actor_id": actor_id,
        "details": {"tenant_id": "tenant-a"},
    }


def _change_set(change_id="change-atomic"):
    change_set = GitOpsEngine().create_change_set(
        source_action_id=f"action-{change_id}",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-atomic",
                field="instance_type",
                desired_value="t3.large",
                current_value="t3.medium",
                reason="Atomic GitOps integration test.",
            )
        ],
    )
    change_set.change_id = change_id
    change_set.metadata["tenant_id"] = "tenant-a"
    return change_set


def test_action_plan_and_audit_event_commit_together(shared_database_url):
    store = ActionPlanStore(database_url=shared_database_url)
    trail = PersistentAuditTrail(shared_database_url)
    try:
        store.save_many(
            [_plan()],
            "tenant-a",
            audit_trail=trail,
            audit_events=[_audit_event("plan-atomic")],
        )
        assert store.get("plan-atomic") is not None
        assert [event.action_id for event in trail.get_events()] == ["plan-atomic"]
        assert trail.verify_integrity()
    finally:
        store.close()
        trail.close()


def test_action_plan_rolls_back_when_audit_append_fails(shared_database_url):
    store = ActionPlanStore(database_url=shared_database_url)
    trail = PersistentAuditTrail(shared_database_url)
    try:
        invalid_event = _audit_event("plan-rollback", actor_id="")
        with pytest.raises(ValueError, match="actor_id cannot be empty"):
            store.save_many(
                [_plan("plan-rollback")],
                "tenant-a",
                audit_trail=trail,
                audit_events=[invalid_event],
            )

        assert store.get("plan-rollback") is None
        assert trail.get_events() == []
        engine = create_engine(shared_database_url, future=True)
        try:
            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT last_created_order FROM action_plan_state")
                ).scalar_one() == 0
        finally:
            engine.dispose()
    finally:
        store.close()
        trail.close()


def test_gitops_registration_and_audit_event_commit_together(shared_database_url):
    trail = PersistentAuditTrail(shared_database_url)
    registry = GitOpsChangeSetRegistry(
        database_url=shared_database_url,
        audit_trail=trail,
    )
    try:
        change_set = _change_set()
        registry.register(change_set, actor_id="operator-a")
        assert registry.get(change_set.change_id) is not None
        events = trail.get_events()
        assert len(events) == 1
        assert events[0].event == "gitops_change_registered"
        assert events[0].actor_id == "operator-a"
        assert trail.verify_integrity()
    finally:
        registry.close()
        trail.close()


def test_gitops_registration_rolls_back_when_audit_append_fails(shared_database_url):
    trail = PersistentAuditTrail(shared_database_url)
    registry = GitOpsChangeSetRegistry(
        database_url=shared_database_url,
        audit_trail=trail,
    )
    try:
        with pytest.raises(ValueError, match="actor_id cannot be empty"):
            registry.register(_change_set("change-rollback"), actor_id="")

        assert registry.get("change-rollback") is None
        assert trail.get_events() == []
        engine = create_engine(shared_database_url, future=True)
        try:
            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT last_created_order FROM gitops_state")
                ).scalar_one() == 0
        finally:
            engine.dispose()
    finally:
        registry.close()
        trail.close()


def test_gitops_transition_rolls_back_when_audit_append_fails(shared_database_url):
    trail = PersistentAuditTrail(shared_database_url)
    registry = GitOpsChangeSetRegistry(
        database_url=shared_database_url,
        audit_trail=trail,
    )
    try:
        change_set = _change_set("change-transition-rollback")
        registry.register(change_set, actor_id="operator-a")
        with pytest.raises(ValueError, match="actor_id cannot be empty"):
            registry.approve(change_set.change_id, "operator-b", actor_id="")

        refreshed = registry.get(change_set.change_id)
        assert refreshed.status == GitOpsChangeStatus.PENDING_APPROVAL
        assert [event.event for event in trail.get_events()] == [
            "gitops_change_registered"
        ]
        assert trail.verify_integrity()
    finally:
        registry.close()
        trail.close()
