from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_ec2_planning_endpoint_returns_action_plans():
    insight = {
        "type": "high_cpu_utilization",
        "severity": "high",
        "message": "CPU utilization is high.",
        "recommendation": "Investigate CPU capacity.",
    }

    with patch("autonomy.api.aws_service.get_ec2_insights") as get_insights:
        get_insights.return_value = {
            "status": "healthy",
            "instance_id": "i-12345678",
            "insights": [insight],
        }

        response = client.get("/autonomy/ec2/instances/i-12345678/plans")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["plan_count"] == 1
    assert body["plans"][0]["action_type"] == "investigate_cpu_capacity"
    assert body["plans"][0]["requires_approval"] is True


def test_ec2_planning_endpoint_skips_unknown_insight():
    insight = {
        "type": "unknown_future_insight",
        "severity": "low",
        "message": "Unsupported insight.",
    }

    with patch("autonomy.api.aws_service.get_ec2_insights") as get_insights:
        get_insights.return_value = {
            "status": "healthy",
            "instance_id": "i-12345678",
            "insights": [insight],
        }

        response = client.get("/autonomy/ec2/instances/i-12345678/plans")

    assert response.status_code == 200
    assert response.json()["plan_count"] == 0


def test_ec2_planning_endpoint_returns_403_for_unhealthy_aws_result():
    with patch("autonomy.api.aws_service.get_ec2_insights") as get_insights:
        get_insights.return_value = {
            "status": "unhealthy",
            "error": "AWS unavailable",
        }

        response = client.get("/autonomy/ec2/instances/i-12345678/plans")

    assert response.status_code == 403
    assert response.json()["detail"] == "AWS unavailable"


def test_s3_planning_endpoint_returns_action_plans():
    insight = {
        "type": "large_object",
        "severity": "medium",
        "message": "Large object found.",
        "recommendation": "Review the object.",
    }

    with patch("autonomy.api.aws_service.get_s3_bucket_insights") as get_insights:
        get_insights.return_value = {
            "status": "healthy",
            "bucket": "example-bucket",
            "insights": [insight],
        }

        response = client.get(
            "/autonomy/s3/buckets/example-bucket/plans?prefix=logs/&max_keys=100"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["plan_count"] == 1
    assert body["plans"][0]["action_type"] == "review_large_object"
    assert body["plans"][0]["target"]["resource_id"] == "example-bucket"
    assert body["plans"][0]["requires_approval"] is True


def test_s3_planning_endpoint_rejects_invalid_max_keys():
    response = client.get(
        "/autonomy/s3/buckets/example-bucket/plans?max_keys=1001"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "max_keys must be between 1 and 1000"


def test_s3_planning_endpoint_returns_403_for_unhealthy_aws_result():
    with patch("autonomy.api.aws_service.get_s3_bucket_insights") as get_insights:
        get_insights.return_value = {
            "status": "unhealthy",
            "error": "Access denied",
        }

        response = client.get("/autonomy/s3/buckets/example-bucket/plans")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
