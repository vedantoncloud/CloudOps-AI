from fastapi.testclient import TestClient

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.api import _plan_registry
from main import app


client = TestClient(app)


def create_approved_action(*, rollback_available=False):
    action = ActionPlan(
        action_type="investigate_cpu_capacity",
        target=ActionTarget(
            resource_type="ec2",
            resource_id="i-test-execution",
        ),
        reason="Test autonomous execution",
        risk=RiskLevel.LOW,
        requires_approval=True,
        rollback_available=rollback_available,
    )
    action.status = ActionStatus.APPROVED
    _plan_registry[action.action_id] = action
    return action


def test_execute_unknown_action_returns_404():
    response = client.post("/autonomy/plans/act-does-not-exist/execute")
    assert response.status_code == 404


def test_execute_unapproved_action_returns_409():
    action = create_approved_action()
    action.status = ActionStatus.PENDING_APPROVAL

    response = client.post(
        f"/autonomy/plans/{action.action_id}/execute"
    )

    assert response.status_code == 409


def test_execute_invalid_dry_run_returns_400():
    action = create_approved_action()

    response = client.post(
        f"/autonomy/plans/{action.action_id}/execute",
        params={"dry_run": "invalid"},
    )

    assert response.status_code == 400


def test_execute_real_mode_is_blocked():
    action = create_approved_action()

    response = client.post(
        f"/autonomy/plans/{action.action_id}/execute",
        params={"dry_run": "false"},
    )

    assert response.status_code == 400


def test_execute_approved_action_succeeds():
    action = create_approved_action()

    response = client.post(
        f"/autonomy/plans/{action.action_id}/execute"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "healthy"
    assert body["action"]["action_id"] == action.action_id
    assert body["action"]["status"] == "succeeded"

    assert body["execution"]["action_id"] == action.action_id
    assert body["execution"]["dry_run"] is True
    assert body["execution"]["executed"] is False
    assert body["execution"]["successful"] is True


def test_execute_requires_approval():
    action = create_approved_action()
    action.status = ActionStatus.PLANNED

    response = client.post(
        f"/autonomy/plans/{action.action_id}/execute"
    )

    assert response.status_code == 409


def test_execute_defaults_to_dry_run():
    action = create_approved_action()

    response = client.post(
        f"/autonomy/plans/{action.action_id}/execute"
    )

    assert response.status_code == 200
    assert response.json()["execution"]["dry_run"] is True
    assert response.json()["execution"]["executed"] is False


def test_execute_returns_execution_details():
    action = create_approved_action()

    response = client.post(
        f"/autonomy/plans/{action.action_id}/execute"
    )

    assert response.status_code == 200

    execution = response.json()["execution"]

    assert execution["details"]["action_type"] == action.action_type
    assert execution["details"]["resource_type"] == "ec2"
    assert execution["details"]["resource_id"] == "i-test-execution"
