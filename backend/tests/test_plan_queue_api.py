from types import SimpleNamespace

from fastapi.testclient import TestClient

from autonomy import api
from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from main import app


client = TestClient(app)


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


def test_plan_queue_rejects_invalid_pagination():
    response = client.get("/autonomy/plans?limit=201")

    assert response.status_code == 422
