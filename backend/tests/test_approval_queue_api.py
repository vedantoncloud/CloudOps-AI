from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy import api


def _plan(action_id: str, status: ActionStatus) -> ActionPlan:
    plan = ActionPlan(
        action_type="review_instance_state",
        target=ActionTarget(resource_type="ec2_instance", resource_id=action_id),
        reason="Review the instance state.",
        risk=RiskLevel.LOW,
    )
    plan.action_id = action_id
    plan.status = status
    return plan


def _request(tenant_id: str | None = None):
    return SimpleNamespace(state=SimpleNamespace(
        tenant_scoped=tenant_id is not None,
        tenant_id=tenant_id,
    ))


def test_approval_queue_filters_pending_and_paginates(monkeypatch):
    plans = {
        "pending-old": _plan("pending-old", ActionStatus.PENDING_APPROVAL),
        "approved": _plan("approved", ActionStatus.APPROVED),
        "pending-new": _plan("pending-new", ActionStatus.PENDING_APPROVAL),
    }
    monkeypatch.setattr(api, "_plan_registry", plans)
    monkeypatch.setattr(api, "_plan_tenants", {key: "tenant-a" for key in plans})

    first_page = api.list_pending_approvals(_request("tenant-a"), limit=1)
    second_page = api.list_pending_approvals(_request("tenant-a"), limit=1, offset=1)

    assert first_page["total"] == 2
    assert first_page["approvals"][0]["action_id"] == "pending-new"
    assert second_page["approvals"][0]["action_id"] == "pending-old"


def test_approval_queue_is_scoped_to_authenticated_tenant(monkeypatch):
    plans = {
        "a": _plan("a", ActionStatus.PENDING_APPROVAL),
        "b": _plan("b", ActionStatus.PENDING_APPROVAL),
    }
    monkeypatch.setattr(api, "_plan_registry", plans)
    monkeypatch.setattr(api, "_plan_tenants", {"a": "tenant-a", "b": "tenant-b"})

    result = api.list_pending_approvals(_request("tenant-a"))

    assert result["total"] == 1
    assert [item["action_id"] for item in result["approvals"]] == ["a"]


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_approval_queue_rejects_invalid_pagination(kwargs):
    with pytest.raises(HTTPException) as error:
        api.list_pending_approvals(_request(), **kwargs)

    assert error.value.status_code == 422
