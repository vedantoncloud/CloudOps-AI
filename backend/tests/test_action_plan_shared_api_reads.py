"""Shared action-plan API reads must refresh across application workers."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from alembic import command
from alembic.config import Config

from autonomy import api
from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.action_plan_store import ActionPlanStore


@pytest.fixture
def shared_stores(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'shared-action-plans-api.db'}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    writer = ActionPlanStore(database_url=url)
    reader = ActionPlanStore(database_url=url)
    monkeypatch.setattr(api, "action_plan_store", reader)
    monkeypatch.setattr(api, "_plan_registry", {})
    monkeypatch.setattr(api, "_plan_tenants", {})
    yield writer, reader
    writer.close()
    reader.close()
    command.downgrade(config, "base")


def _plan(action_id: str, status: ActionStatus = ActionStatus.PENDING_APPROVAL):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget("ec2_instance", f"i-{action_id}"),
        reason="Review the instance state.",
        risk=RiskLevel.MEDIUM,
        status=status,
    )


def _request(tenant_id: str | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(
            tenant_scoped=tenant_id is not None,
            tenant_id=tenant_id,
        )
    )


def test_shared_plan_detail_refreshes_from_another_worker(shared_stores):
    writer, _reader = shared_stores
    writer.save_many([_plan("cross-worker")], "tenant-a")

    result = api.get_plan("cross-worker", _request("tenant-a"))

    assert result["action"]["action_id"] == "cross-worker"
    assert result["action"]["status"] == ActionStatus.PENDING_APPROVAL.value
    # Tenant-scoped repository reads do not populate the process-wide cache.
    assert "cross-worker" not in api._plan_registry
    assert "cross-worker" not in api._plan_tenants


def test_shared_plan_list_and_approval_queue_refresh_after_remote_transition(shared_stores):
    writer, _reader = shared_stores
    writer.save_many([_plan("remote-transition")], "tenant-a")

    # Prime the API cache with the pending state, then update through another
    # worker. The next list/queue request must observe the committed SQL state.
    assert api.list_pending_approvals(_request("tenant-a"))["total"] == 1
    writer.save_many(
        [_plan("remote-transition", ActionStatus.APPROVED)],
        "tenant-a",
    )

    pending = api.list_pending_approvals(_request("tenant-a"))
    approved = api.list_plans(_request("tenant-a"), status=ActionStatus.APPROVED)

    assert pending["total"] == 0
    assert approved["total"] == 1
    assert approved["plans"][0]["status"] == ActionStatus.APPROVED.value


def test_shared_refresh_replaces_stale_cache_and_preserves_tenant_isolation(shared_stores):
    writer, _reader = shared_stores
    writer.save_many([_plan("owned-plan")], "tenant-a")
    api._plan_registry["stale-cache-only"] = _plan("stale-cache-only")
    api._plan_tenants["stale-cache-only"] = "tenant-a"

    listed = api.list_plans(_request("tenant-a"))

    assert listed["total"] == 1
    assert [item["action_id"] for item in listed["plans"]] == ["owned-plan"]
    # A tenant-scoped read must not replace the process-wide cache.
    assert "stale-cache-only" in api._plan_registry
    api.list_plans(_request())
    assert "stale-cache-only" not in api._plan_registry
    with pytest.raises(HTTPException) as error:
        api.get_plan("owned-plan", _request("tenant-b"))
    assert error.value.status_code == 404


def test_shared_plan_lifecycle_write_rejects_stale_worker_and_returns_conflict(
    shared_stores, monkeypatch
):
    writer, _reader = shared_stores
    writer.save_many([_plan("stale-write")], "tenant-a")

    # This API worker loads a pending snapshot before another worker commits
    # the approval. Its later transition must not overwrite that decision.
    stale_plan = api._get_plan("stale-write", _request("tenant-a"))
    assert stale_plan.status == ActionStatus.PENDING_APPROVAL
    writer.save_many([_plan("stale-write", ActionStatus.APPROVED)], "tenant-a")
    monkeypatch.setattr(api, "audit_trail", SimpleNamespace(record=lambda **_event: None))

    with pytest.raises(HTTPException) as error:
        api._persist_plan(
            stale_plan,
            {
                "old_status": ActionStatus.PENDING_APPROVAL.value,
                "new_status": ActionStatus.APPROVED.value,
                "details": {"tenant_id": "tenant-a"},
            },
        )

    assert error.value.status_code == 409
    persisted, tenant = writer.get("stale-write")
    assert persisted.status == ActionStatus.APPROVED
    assert tenant == "tenant-a"


def test_shared_store_load_all_applies_tenant_filter_in_repository(shared_stores):
    writer, reader = shared_stores
    writer.save_many([_plan("tenant-a-plan")], "tenant-a")
    writer.save_many([_plan("tenant-b-plan")], "tenant-b")

    tenant_a = reader.load_all(tenant_id="tenant-a", tenant_scoped=True)
    tenant_b = reader.load_all(tenant_id="tenant-b", tenant_scoped=True)

    assert [plan.action_id for plan, _tenant in tenant_a] == ["tenant-a-plan"]
    assert [plan.action_id for plan, _tenant in tenant_b] == ["tenant-b-plan"]


def test_shared_tenant_reads_do_not_pollute_process_wide_cache(shared_stores):
    writer, _reader = shared_stores
    writer.save_many([_plan("visible-to-a")], "tenant-a")
    writer.save_many([_plan("visible-to-b")], "tenant-b")

    tenant_a = api.list_plans(_request("tenant-a"))
    tenant_b = api.list_plans(_request("tenant-b"))

    assert [item["action_id"] for item in tenant_a["plans"]] == ["visible-to-a"]
    assert [item["action_id"] for item in tenant_b["plans"]] == ["visible-to-b"]
    assert api._plan_registry == {}
    assert api._plan_tenants == {}
