from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from autonomy import api
from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_plan_registry():
    with api._registry_lock:
        original_registry = api._plan_registry.copy()
        original_tenants = api._plan_tenants.copy()
        api._plan_registry.clear()
        api._plan_tenants.clear()
    try:
        yield
    finally:
        with api._registry_lock:
            api._plan_registry.clear()
            api._plan_registry.update(original_registry)
            api._plan_tenants.clear()
            api._plan_tenants.update(original_tenants)


def _plan(action_id, status=ActionStatus.PENDING_APPROVAL):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget("ec2_instance", f"i-{action_id}"),
        reason="Review instance state",
        risk=RiskLevel.MEDIUM,
        status=status,
    )


def test_plan_queue_filters_status_and_paginates():
    api._store_plans([_plan("queue-a"), _plan("queue-b", ActionStatus.APPROVED)])

    response = client.get("/autonomy/plans?status=pending_approval&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert [plan["action_id"] for plan in body["plans"]] == ["queue-a"]


def test_plan_queue_hides_other_tenants_and_plan_lookup_returns_not_found():
    api._store_plans([_plan("tenant-private")], tenant_id="tenant-a")
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-b"))

    assert api._get_plan("tenant-private", request) is None
    visible = api.list_plans(request)
    assert all(plan["action_id"] != "tenant-private" for plan in visible["plans"])


def test_get_plan_returns_current_serialized_state_for_owner():
    plan = _plan("detail-a", ActionStatus.APPROVED)
    api._store_plans([plan], tenant_id="tenant-a")
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-a"))

    result = api.get_plan("detail-a", request)

    assert result["status"] == "healthy"
    assert result["action"]["action_id"] == "detail-a"
    assert result["action"]["status"] == "approved"
    assert result["action"]["target"]["resource_id"] == "i-detail-a"


def test_get_plan_hides_missing_and_foreign_tenant_plans():
    from fastapi import HTTPException
    import pytest

    api._store_plans([_plan("detail-private")], tenant_id="tenant-a")
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-b"))

    for action_id in ("detail-private", "does-not-exist"):
        with pytest.raises(HTTPException) as error:
            api.get_plan(action_id, request)
        assert error.value.status_code == 404


def test_plan_queue_rejects_invalid_pagination():
    response = client.get("/autonomy/plans?limit=201")

    assert response.status_code == 422
