from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from main import app
from services.aws_service import AWSService


def test_s3_bucket_prefix_is_sent_to_aws_and_preserves_page_cursor():
    with patch("services.aws_service.boto3.client") as make_client:
        s3 = make_client.return_value
        s3.list_buckets.return_value = {
            "Buckets": [{"Name": "logs-prod"}],
            "ContinuationToken": "next-page",
        }

        result = AWSService().get_s3_buckets(100, "current-page", prefix="logs-")

    s3.list_buckets.assert_called_once_with(
        MaxBuckets=100, ContinuationToken="current-page", Prefix="logs-"
    )
    assert result == {
        "service": "s3",
        "status": "healthy",
        "buckets": [{"name": "logs-prod", "creation_date": None}],
        "is_truncated": True,
        "next_continuation_token": "next-page",
    }


def test_s3_bucket_prefix_endpoint_forwards_prefix_and_cursor():
    with patch("main.aws_service.get_s3_buckets", return_value={
        "status": "healthy", "buckets": [], "is_truncated": False,
    }) as list_buckets:
        response = TestClient(app).get(
            "/cloud/aws/s3/buckets",
            params={"prefix": "logs-", "continuation_token": "cursor", "max_buckets": 25},
        )

    assert response.status_code == 200
    list_buckets.assert_called_once_with(25, "cursor", prefix="logs-")


def test_s3_bucket_prefix_validation_rejects_blank_and_oversized_values_before_aws():
    with patch("main.aws_service.get_s3_buckets") as list_buckets:
        client = TestClient(app)
        assert client.get("/cloud/aws/s3/buckets", params={"prefix": "  "}).status_code == 400
        assert client.get("/cloud/aws/s3/buckets", params={"prefix": "x" * 256}).status_code == 400

    list_buckets.assert_not_called()


def test_s3_bucket_prefix_provider_failure_is_sanitized():
    with patch("main.aws_service.get_s3_buckets", return_value={
        "status": "unhealthy", "error": "private AWS diagnostic",
    }):
        response = TestClient(app).get("/cloud/aws/s3/buckets?prefix=logs-")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "private AWS diagnostic" not in response.text


def test_s3_bucket_prefix_service_reports_provider_failure():
    with patch("services.aws_service.boto3.client") as make_client:
        make_client.return_value.list_buckets.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "temporarily unavailable"}},
            "ListBuckets",
        )

        result = AWSService().get_s3_buckets(prefix="logs-")

    assert result["status"] == "unhealthy"
    assert "temporarily unavailable" in result["error"]
