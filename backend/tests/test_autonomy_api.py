from unittest.mock import patch

from fastapi.testclient import TestClient

from autonomy.action_models import ActionStatus, ActionTarget, ActionPlan, RiskLevel
from main import app


client = TestClient(app)


def _plan():
    return ActionPlan(
        action_type="review_instance_state",
        target=ActionTarget(
            resource_type="ec2_instance",
            resource_id="i-123456789",
        ),
        reason="Instance is not running.",
        risk=RiskLevel.MEDIUM,
    )


def test_evaluate_plan_moves_action_to_pending_approval():
    plan = _plan()

    with patch("autonomy.api.aws_service") as mock_service:
        mock_service.get_ec2_insights.return_value = {
            "status": "healthy",
            "insights": [
                {
                    "type": "instance_not_running",
                    "severity": "medium",
                    "message": "Instance is not running.",
                }
            ],
        }

        with patch("autonomy.api.action_planner") as mock_planner:
            mock_planner.plan_from_ec2_insights.return_value = [plan]

            response = client.get(
                "/autonomy/ec2/instances/i-123456789/plans"
            )

    assert response.status_code == 200
    action_id = response.json()["plans"][0]["action_id"]

    response = client.post(f"/autonomy/plans/{action_id}/evaluate")

    assert response.status_code == 200
    assert response.json()["action"]["status"] == ActionStatus.PENDING_APPROVAL.value
    assert response.json()["action"]["requires_approval"] is True


def test_approve_plan_after_policy_evaluation():
    plan = _plan()

    with patch("autonomy.api.aws_service") as mock_service:
        mock_service.get_ec2_insights.return_value = {
            "status": "healthy",
            "insights": [
                {
                    "type": "instance_not_running",
                    "severity": "medium",
                    "message": "Instance is not running.",
                }
            ],
        }

        with patch("autonomy.api.action_planner") as mock_planner:
            mock_planner.plan_from_ec2_insights.return_value = [plan]

            response = client.get(
                "/autonomy/ec2/instances/i-123456789/plans"
            )

    action_id = response.json()["plans"][0]["action_id"]

    client.post(f"/autonomy/plans/{action_id}/evaluate")
    response = client.post(f"/autonomy/plans/{action_id}/approve")

    assert response.status_code == 200
    assert response.json()["action"]["status"] == ActionStatus.APPROVED.value


def test_cancel_plan_after_policy_evaluation():
    plan = _plan()

    with patch("autonomy.api.aws_service") as mock_service:
        mock_service.get_ec2_insights.return_value = {
            "status": "healthy",
            "insights": [
                {
                    "type": "instance_not_running",
                    "severity": "medium",
                    "message": "Instance is not running.",
                }
            ],
        }

        with patch("autonomy.api.action_planner") as mock_planner:
            mock_planner.plan_from_ec2_insights.return_value = [plan]

            response = client.get(
                "/autonomy/ec2/instances/i-123456789/plans"
            )

    action_id = response.json()["plans"][0]["action_id"]

    client.post(f"/autonomy/plans/{action_id}/evaluate")
    response = client.post(f"/autonomy/plans/{action_id}/cancel")

    assert response.status_code == 200
    assert response.json()["action"]["status"] == ActionStatus.CANCELLED.value


def test_approve_before_evaluation_is_rejected():
    plan = _plan()

    with patch("autonomy.api.aws_service") as mock_service:
        mock_service.get_ec2_insights.return_value = {
            "status": "healthy",
            "insights": [
                {
                    "type": "instance_not_running",
                    "severity": "medium",
                    "message": "Instance is not running.",
                }
            ],
        }

        with patch("autonomy.api.action_planner") as mock_planner:
            mock_planner.plan_from_ec2_insights.return_value = [plan]

            response = client.get(
                "/autonomy/ec2/instances/i-123456789/plans"
            )

    action_id = response.json()["plans"][0]["action_id"]

    response = client.post(f"/autonomy/plans/{action_id}/approve")

    assert response.status_code == 409


def test_cancel_already_approved_plan_is_rejected():
    plan = _plan()

    with patch("autonomy.api.aws_service") as mock_service:
        mock_service.get_ec2_insights.return_value = {
            "status": "healthy",
            "insights": [
                {
                    "type": "instance_not_running",
                    "severity": "medium",
                    "message": "Instance is not running.",
                }
            ],
        }

        with patch("autonomy.api.action_planner") as mock_planner:
            mock_planner.plan_from_ec2_insights.return_value = [plan]

            response = client.get(
                "/autonomy/ec2/instances/i-123456789/plans"
            )

    action_id = response.json()["plans"][0]["action_id"]

    client.post(f"/autonomy/plans/{action_id}/evaluate")
    client.post(f"/autonomy/plans/{action_id}/approve")
    response = client.post(f"/autonomy/plans/{action_id}/cancel")

    assert response.status_code == 409


def test_unknown_action_id_returns_404():
    response = client.post("/autonomy/plans/act-does-not-exist/evaluate")

    assert response.status_code == 404
