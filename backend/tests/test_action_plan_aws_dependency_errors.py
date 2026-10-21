from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


@pytest.mark.parametrize(
    ("path", "provider_method", "provider_args"),
    [
        (
            "/autonomy/ec2/instances/i-123456789/plans",
            "get_ec2_insights",
            ("i-123456789",),
        ),
        (
            "/autonomy/s3/buckets/example-bucket/plans",
            "get_s3_bucket_insights",
            ("example-bucket",),
        ),
    ],
)
def test_plan_creation_returns_plan_for_healthy_provider(path, provider_method, provider_args):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner, patch("autonomy.api._plan_response", return_value={"plans": []}) as response:
        getattr(aws, provider_method).return_value = {"status": "healthy", "insights": []}
        planner_method = (
            "plan_from_ec2_insights" if provider_method == "get_ec2_insights"
            else "plan_from_s3_insights"
        )
        getattr(planner, planner_method).return_value = []

        result = client.post(path)

    assert result.status_code == 200
    assert result.json() == {"plans": []}
    if provider_method == "get_ec2_insights":
        aws.get_ec2_insights.assert_called_once_with(*provider_args)
    else:
        aws.get_s3_bucket_insights.assert_called_once_with(
            *provider_args, prefix=None, max_keys=None
        )
    response.assert_called_once()


@pytest.mark.parametrize(
    ("path", "provider_method", "provider_args"),
    [
        (
            "/autonomy/ec2/instances/i-123456789/plans",
            "get_ec2_insights",
            ("i-123456789",),
        ),
        (
            "/autonomy/s3/buckets/example-bucket/plans",
            "get_s3_bucket_insights",
            ("example-bucket",),
        ),
    ],
)
def test_plan_creation_sanitizes_provider_failures_as_service_unavailable(
    path, provider_method, provider_args
):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner, patch("autonomy.api._plan_response") as response:
        getattr(aws, provider_method).return_value = {
            "status": "unhealthy",
            "error": "AccessDenied for account 123456789012",
        }

        result = client.post(path)

    assert result.status_code == 503
    assert result.json() == {"detail": "AWS resource data is unavailable"}
    assert "123456789012" not in result.text
    getattr(aws, provider_method).assert_called_once()
    planner.assert_not_called()
    response.assert_not_called()


@pytest.mark.parametrize(
    ("path", "provider_method"),
    [
        ("/autonomy/ec2/instances/i-123456789/plans", "get_ec2_insights"),
        ("/autonomy/s3/buckets/example-bucket/plans", "get_s3_bucket_insights"),
    ],
)
@pytest.mark.parametrize(
    "provider_result",
    [None, {"status": "healthy"}, {"status": "healthy", "insights": None}],
)
def test_plan_creation_fails_closed_on_malformed_provider_payload(
    path, provider_method, provider_result
):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner:
        getattr(aws, provider_method).return_value = provider_result

        result = client.post(path)

    assert result.status_code == 503
    assert result.json() == {"detail": "AWS resource data is unavailable"}
    planner_method = (
        "plan_from_ec2_insights" if provider_method == "get_ec2_insights"
        else "plan_from_s3_insights"
    )
    getattr(planner, planner_method).assert_not_called()


@pytest.mark.parametrize(
    ("path", "provider_method"),
    [
        ("/autonomy/ec2/instances/i-123456789/plans", "get_ec2_insights"),
        ("/autonomy/s3/buckets/example-bucket/plans", "get_s3_bucket_insights"),
    ],
)
def test_plan_creation_sanitizes_thrown_provider_exception(path, provider_method):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner:
        getattr(aws, provider_method).side_effect = RuntimeError(
            "AccessDenied for account 123456789012"
        )

        result = client.post(path)

    assert result.status_code == 503
    assert result.json() == {"detail": "AWS resource data is unavailable"}
    assert "123456789012" not in result.text
    planner_method = (
        "plan_from_ec2_insights" if provider_method == "get_ec2_insights"
        else "plan_from_s3_insights"
    )
    getattr(planner, planner_method).assert_not_called()


def test_s3_plan_rejects_out_of_range_scan_limit_before_provider_call():
    with patch("autonomy.api.aws_service") as aws:
        result = client.post("/autonomy/s3/buckets/example-bucket/plans?max_keys=1001")

    assert result.status_code == 400
    assert result.json() == {"detail": "max_keys must be between 1 and 1000"}
    aws.get_s3_bucket_insights.assert_not_called()
