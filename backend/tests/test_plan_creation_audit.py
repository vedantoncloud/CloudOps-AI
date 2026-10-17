from types import SimpleNamespace

import pytest

from autonomy import api
from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel


@pytest.fixture(autouse=True)
def isolate_plan_registry():
    with api._registry_lock:
        registry = api._plan_registry.copy()
        tenants = api._plan_tenants.copy()
        api._plan_registry.clear()
        api._plan_tenants.clear()
    try:
        yield
    finally:
        with api._registry_lock:
            api._plan_registry.clear()
            api._plan_registry.update(registry)
            api._plan_tenants.clear()
            api._plan_tenants.update(tenants)


def _plan(action_id="plan-a"):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget("ec2_instance", "i-12345678"),
        reason="Review instance state",
        risk=RiskLevel.LOW,
        status=ActionStatus.PLANNED,
    )


def _request(*, principal=None, tenant_id=None):
    return SimpleNamespace(
        state=SimpleNamespace(
            tenant_scoped=tenant_id is not None,
            tenant_id=tenant_id,
            principal=principal,
        )
    )


def test_plan_creation_records_actor_and_tenant_before_exposing_plan(monkeypatch):
    recorded = []

    class Trail:
        def record(self, **event):
            recorded.append(event)

    monkeypatch.setattr(api, "audit_trail", Trail())
    plan = _plan()

    response = api._plan_response(
        [plan], _request(principal=SimpleNamespace(subject="operator-7"), tenant_id="team-a")
    )

    assert response["plan_count"] == 1
    assert recorded == [{
        "action_id": "plan-a",
        "action_type": "review_instance_state",
        "resource_type": "ec2_instance",
        "resource_id": "i-12345678",
        "old_status": "none",
        "new_status": "planned",
        "event": "plan_created",
        "actor_id": "operator-7",
        "details": {"tenant_id": "team-a"},
    }]
    assert api._plan_registry["plan-a"] is plan
    assert api._plan_tenants["plan-a"] == "team-a"


def test_plan_creation_without_authenticated_principal_is_audited_as_unattributed(monkeypatch):
    recorded = []

    class Trail:
        def record(self, **event):
            recorded.append(event)

    monkeypatch.setattr(api, "audit_trail", Trail())
    api._plan_response([_plan("development-plan")], _request())

    assert len(recorded) == 1
    assert recorded[0]["actor_id"] is None
    assert recorded[0]["details"] == {}


def test_empty_plan_result_does_not_write_an_audit_event(monkeypatch):
    class Trail:
        def record(self, **event):
            pytest.fail("empty results must not create audit events")

    monkeypatch.setattr(api, "audit_trail", Trail())

    assert api._plan_response([], _request())["plan_count"] == 0


def test_audit_storage_failure_prevents_plan_from_becoming_visible(monkeypatch):
    class Trail:
        def record(self, **event):
            raise OSError("audit store unavailable")

    monkeypatch.setattr(api, "audit_trail", Trail())
    plan = _plan("unlogged-plan")

    with pytest.raises(OSError, match="audit store unavailable"):
        api._plan_response([plan], _request())

    assert "unlogged-plan" not in api._plan_registry
