from types import SimpleNamespace

import pytest

from autonomy import api
from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel


def _plan(status=ActionStatus.PENDING_APPROVAL):
    return ActionPlan(
        action_id="decision-audit-plan",
        action_type="review_instance_state",
        target=ActionTarget("ec2_instance", "i-12345678"),
        reason="Review state",
        risk=RiskLevel.LOW,
        status=status,
    )


def _request():
    return SimpleNamespace(state=SimpleNamespace(
        principal=SimpleNamespace(subject="operator-9"),
        tenant_scoped=True,
        tenant_id="team-blue",
    ))


@pytest.mark.parametrize(
    ("operation", "expected_status", "event", "payload"),
    [
        (api.approve_plan, ActionStatus.APPROVED, "plan_approved", None),
        (api.reject_plan, ActionStatus.REJECTED, "plan_rejected", api.RejectionRequest(reason="Not safe")),
        (api.cancel_plan, ActionStatus.CANCELLED, "plan_cancelled", None),
    ],
)
def test_plan_decision_writes_durable_actor_and_tenant_audit(
    monkeypatch, operation, expected_status, event, payload
):
    plan = _plan()
    monkeypatch.setattr(api, "_get_plan", lambda action_id, request: plan)
    monkeypatch.setattr(api, "_persist_plan", lambda action: None)
    recorded = []

    class Trail:
        def record(self, **entry):
            recorded.append(entry)

    monkeypatch.setattr(api, "audit_trail", Trail())
    if payload is None:
        response = operation(plan.action_id, _request())
    else:
        response = operation(plan.action_id, payload, _request())

    assert response["action"]["status"] == expected_status.value
    assert recorded == [{
        "action_id": plan.action_id,
        "action_type": plan.action_type,
        "resource_type": "ec2_instance",
        "resource_id": "i-12345678",
        "old_status": "pending_approval",
        "new_status": expected_status.value,
        "event": event,
        "actor_id": "operator-9",
        "details": {"tenant_id": "team-blue"},
    }]


def test_invalid_decision_does_not_write_audit_event(monkeypatch):
    plan = _plan(ActionStatus.APPROVED)
    monkeypatch.setattr(api, "_get_plan", lambda action_id, request: plan)

    class Trail:
        def record(self, **entry):
            pytest.fail("invalid transitions must not be audited as successful")

    monkeypatch.setattr(api, "audit_trail", Trail())
    with pytest.raises(Exception):
        api.cancel_plan(plan.action_id, _request())


def test_plan_evaluation_records_actor_and_tenant(monkeypatch):
    plan = _plan(ActionStatus.PLANNED)
    monkeypatch.setattr(api, "_get_plan", lambda action_id, request: plan)
    monkeypatch.setattr(api, "_persist_plan", lambda action: None)
    recorded = []

    class Trail:
        def record(self, **entry):
            recorded.append(entry)

    monkeypatch.setattr(api, "audit_trail", Trail())

    response = api.evaluate_plan(plan.action_id, _request())

    assert response["action"]["status"] == "pending_approval"
    assert recorded == [{
        "action_id": plan.action_id,
        "action_type": plan.action_type,
        "resource_type": "ec2_instance",
        "resource_id": "i-12345678",
        "old_status": "planned",
        "new_status": "pending_approval",
        "event": "plan_pending_approval",
        "actor_id": "operator-9",
        "details": {"tenant_id": "team-blue"},
    }]


def test_plan_evaluation_persistence_failure_restores_policy_state(monkeypatch):
    plan = _plan(ActionStatus.PLANNED)
    plan.requires_approval = False
    monkeypatch.setattr(api, "_get_plan", lambda action_id, request: plan)
    monkeypatch.setattr(api, "_persist_plan", lambda action: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        api.evaluate_plan(plan.action_id, _request())

    assert plan.status is ActionStatus.PLANNED
    assert plan.requires_approval is False


def test_plan_evaluation_policy_error_restores_partial_changes_without_audit(monkeypatch):
    plan = _plan(ActionStatus.PLANNED)
    plan.requires_approval = False
    monkeypatch.setattr(api, "_get_plan", lambda action_id, request: plan)

    class Policy:
        def evaluate(self, action):
            action.status = ActionStatus.PENDING_APPROVAL
            action.requires_approval = True
            raise ValueError("invalid policy input")

    class Trail:
        def record(self, **entry):
            pytest.fail("failed evaluations must not emit a decision event")

    monkeypatch.setattr(api, "policy_engine", Policy())
    monkeypatch.setattr(api, "audit_trail", Trail())

    with pytest.raises(Exception, match="invalid policy input"):
        api.evaluate_plan(plan.action_id, _request())

    assert plan.status is ActionStatus.PLANNED
    assert plan.requires_approval is False


def test_audit_failure_rolls_back_in_memory_decision(monkeypatch):
    plan = _plan()
    monkeypatch.setattr(api, "_get_plan", lambda action_id, request: plan)

    class Trail:
        def record(self, **entry):
            raise OSError("audit store unavailable")

    monkeypatch.setattr(api, "audit_trail", Trail())
    with pytest.raises(OSError, match="audit store unavailable"):
        api.approve_plan(plan.action_id, _request())

    assert plan.status is ActionStatus.PENDING_APPROVAL
    assert plan.decision_by is None
