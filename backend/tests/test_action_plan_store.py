import sqlite3

import pytest

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.action_plan_store import ActionPlanStore


def _plan(action_id="act-test"):
    return ActionPlan(
        action_id=action_id,
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
            metadata={"region": "us-east-1"},
        ),
        reason="Review the instance state.",
        risk=RiskLevel.MEDIUM,
    )


def test_plan_and_lifecycle_decision_survive_store_recreation(tmp_path):
    path = tmp_path / "plans.sqlite3"
    plan = _plan()
    plan.status = ActionStatus.REJECTED
    plan.decision_by = "operator-a"
    plan.decision_reason = "Outside the maintenance window."

    ActionPlanStore(path).save_many([plan], "tenant-a")
    restored, tenant = ActionPlanStore(path).get(plan.action_id)

    assert tenant == "tenant-a"
    assert restored == plan
    assert ActionPlanStore(path).load_all() == [(plan, "tenant-a")]


def test_save_many_rolls_back_all_plans_when_payload_is_not_serializable(tmp_path):
    store = ActionPlanStore(tmp_path / "plans.sqlite3")
    invalid = _plan("act-invalid")
    invalid.target.metadata["bad"] = object()

    with pytest.raises(TypeError):
        store.save_many([_plan(), invalid], "tenant-a")

    assert store.load_all() == []


def test_unknown_plan_returns_none_and_duplicate_save_keeps_original_order(tmp_path):
    store = ActionPlanStore(tmp_path / "plans.sqlite3")
    first, second = _plan("act-first"), _plan("act-second")
    store.save_many([first, second], None)
    first.status = ActionStatus.PENDING_APPROVAL
    store.save_many([first], None)

    assert store.get("missing") is None
    assert [plan.action_id for plan, _ in store.load_all()] == [
        "act-first", "act-second",
    ]
    assert store.get("act-first")[0].status == ActionStatus.PENDING_APPROVAL


def test_corrupt_plan_payload_fails_closed(tmp_path):
    path = tmp_path / "plans.sqlite3"
    store = ActionPlanStore(path)
    store.save_many([_plan()], "tenant-a")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE action_plans SET payload = ? WHERE action_id = ?",
            ("{invalid", "act-test"),
        )

    with pytest.raises(ValueError):
        store.get("act-test")
