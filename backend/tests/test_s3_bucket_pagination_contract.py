import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import main
from services.aws_service import AWSService


@pytest.mark.parametrize(
    "response,request_cursor",
    [
        ({"Buckets": [], "ContinuationToken": ""}, None),
        ({"Buckets": [], "ContinuationToken": "   "}, None),
        ({"Buckets": [], "ContinuationToken": 123}, None),
        ({"Buckets": [], "ContinuationToken": "same-page"}, "same-page"),
        ({"Buckets": [], "IsTruncated": True}, None),
        ({"Buckets": [], "IsTruncated": False, "ContinuationToken": "next-page"}, None),
        ({"Buckets": [], "IsTruncated": "true", "ContinuationToken": "next-page"}, None),
    ],
)
def test_get_s3_buckets_rejects_malformed_or_inconsistent_pagination(
    response, request_cursor
):
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.list_buckets.return_value = response
        result = AWSService().get_s3_buckets(100, request_cursor)

    assert result["service"] == "s3"
    assert result["status"] == "unhealthy"


def test_get_s3_buckets_rejects_malformed_request_cursor():
    with patch("services.aws_service.boto3.client") as factory:
        result = AWSService().get_s3_buckets(100, "   ")

    assert result["status"] == "unhealthy"
    factory.assert_not_called()


@pytest.mark.parametrize("cursor", ["", "   ", "x" * 4097])
def test_s3_bucket_endpoint_rejects_invalid_request_cursor(cursor):
    response = TestClient(main.app).get(
        "/cloud/aws/s3/buckets",
        params={"continuation_token": cursor},
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("continuation_token must contain")


@pytest.mark.parametrize(
    "result",
    [
        {
            "service": "s3", "status": "healthy", "buckets": [],
            "is_truncated": True, "next_continuation_token": None,
        },
        {
            "service": "s3", "status": "healthy", "buckets": [],
            "is_truncated": False, "next_continuation_token": "orphaned-token",
        },
        {
            "service": "s3", "status": "healthy", "buckets": [],
            "is_truncated": "yes", "next_continuation_token": "next-page",
        },
    ],
)
def test_s3_bucket_endpoint_rejects_inconsistent_provider_pagination(monkeypatch, result):
    monkeypatch.setattr(main.aws_service, "get_s3_buckets", lambda *args, **kwargs: result)

    response = TestClient(main.app).get("/cloud/aws/s3/buckets")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
