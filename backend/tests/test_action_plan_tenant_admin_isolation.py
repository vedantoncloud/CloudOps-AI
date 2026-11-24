from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy import api
from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel


def _plan(action_id: str, *, actor: str) -> ActionPlan:
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget("ec2_instance", f"i-{action_id}"),
        reason="Review the instance state.",
        risk=RiskLevel.MEDIUM,
        status=ActionStatus.PENDING_APPROVAL,
        decision_by=actor,
    )


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={
            "tenant-a-admin": Principal("admin-a", "admin", "tenant-a"),
        },
    )
    app.include_router(api.router)
    return TestClient(app)


def test_tenant_admin_action_plan_reads_stay_within_own_tenant(monkeypatch):
    own_plan = _plan("tenant-a-plan", actor="operator-a")
    same_tenant_other_actor = _plan("tenant-a-other-actor", actor="operator-b")
    foreign_plan = _plan("tenant-b-plan", actor="operator-c")

    monkeypatch.setattr(
        api, "_plan_registry",
        {
            own_plan.action_id: own_plan,
            same_tenant_other_actor.action_id: same_tenant_other_actor,
            foreign_plan.action_id: foreign_plan,
        },
    )
    monkeypatch.setattr(
        api, "_plan_tenants",
        {
            own_plan.action_id: "tenant-a",
            same_tenant_other_actor.action_id: "tenant-a",
            foreign_plan.action_id: "tenant-b",
        },
    )

    client = _client()
    headers = {"Authorization": "Bearer tenant-a-admin"}

    listed = client.get("/autonomy/plans", headers=headers)
    approvals = client.get("/autonomy/approvals", headers=headers)
    own_detail = client.get(
        f"/autonomy/plans/{same_tenant_other_actor.action_id}", headers=headers
    )
    foreign_detail = client.get(
        f"/autonomy/plans/{foreign_plan.action_id}", headers=headers
    )

    assert listed.status_code == 200
    assert {item["action_id"] for item in listed.json()["plans"]} == {
        own_plan.action_id,
        same_tenant_other_actor.action_id,
    }
    assert listed.json()["total"] == 2

    assert approvals.status_code == 200
    assert {item["action_id"] for item in approvals.json()["approvals"]} == {
        own_plan.action_id,
        same_tenant_other_actor.action_id,
    }
    assert approvals.json()["total"] == 2

    assert own_detail.status_code == 200
    assert own_detail.json()["action"]["action_id"] == same_tenant_other_actor.action_id
    assert foreign_detail.status_code == 404
