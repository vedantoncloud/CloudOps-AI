from types import SimpleNamespace
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from services.aws_service import AWSService


def test_bucket_tags_are_returned_as_metadata():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_tagging.return_value = {
            "TagSet": [{"Key": "Environment", "Value": "production"},
                       {"Key": "Owner", "Value": "platform"}]
        }
        result = AWSService().get_s3_bucket_tags("archive")
    assert result == {
        "status": "healthy", "bucket": "archive",
        "tags": {"Environment": "production", "Owner": "platform"},
    }


def test_bucket_without_tags_is_an_empty_success_and_malformed_data_fails_closed():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_tagging.side_effect = ClientError(
            {"Error": {"Code": "NoSuchTagSet", "Message": "none"}}, "GetBucketTagging"
        )
        assert AWSService().get_s3_bucket_tags("archive") == {"status": "healthy", "tags": {}}
        client.return_value.get_bucket_tagging.side_effect = None
        client.return_value.get_bucket_tagging.return_value = {"TagSet": [{"Key": "Owner"}]}
        malformed = AWSService().get_s3_bucket_tags("archive")
    assert malformed["status"] == "unhealthy"


def test_bucket_tag_provider_failure_is_unhealthy():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_tagging.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private detail"}}, "GetBucketTagging"
        )
        result = AWSService().get_s3_bucket_tags("archive")
    assert result["status"] == "unhealthy"


def test_bucket_tags_endpoint_checks_tenant_and_sanitizes_provider_failure(monkeypatch):
    class StubAWS:
        def get_s3_bucket_tags(self, bucket):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": "tenant-a"}}

    monkeypatch.setattr(main, "aws_service", StubAWS())
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-a"))
    response = TestClient(main.app).get("/cloud/aws/s3/buckets/archive/tags")
    assert response.status_code == 200
    assert response.json()["tags"]["CloudOpsTenantId"] == "tenant-a"

    class FailedAWS:
        def get_s3_bucket_tags(self, bucket):
            return {"status": "unhealthy", "error": "private diagnostics"}

    monkeypatch.setattr(main, "aws_service", FailedAWS())
    try:
        main.aws_s3_bucket_tags("archive", request)
        assert False, "failed ownership checks must fail closed"
    except HTTPException as error:
        assert error.status_code == 503


def test_console_bucket_analysis_includes_tags_check():
    html = TestClient(main.app).get("/console").text
    assert "['Tags',`${base}/tags`]" in html
