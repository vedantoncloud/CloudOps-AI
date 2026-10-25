from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import main
from services.aws_service import AWSService


def test_logging_reports_destination_and_prefix():
    configuration = {
        "TargetBucket": "central-logs",
        "TargetPrefix": "source/",
        "TargetGrants": [{"Grantee": {"URI": "group"}, "Permission": "READ"}],
    }
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_logging.return_value = {"LoggingEnabled": configuration}
        result = AWSService().get_s3_bucket_logging("source")

    client.return_value.get_bucket_logging.assert_called_once_with(Bucket="source")
    assert result["status"] == "healthy"
    assert result["configured"] is True
    assert result["destination_bucket"] == "central-logs"
    assert result["destination_prefix"] == "source/"
    assert result["target_grants"] == configuration["TargetGrants"]


def test_logging_without_configuration_is_a_successful_empty_state():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_logging.return_value = {}
        result = AWSService().get_s3_bucket_logging("source")

    assert result == {
        "service": "s3", "status": "healthy", "bucket": "source",
        "configured": False, "destination_bucket": None,
        "destination_prefix": "", "target_grants": [],
    }


def test_logging_provider_failure_and_malformed_configuration_are_unhealthy():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_logging.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private detail"}}, "GetBucketLogging"
        )
        failed = AWSService().get_s3_bucket_logging("source")
        client.return_value.get_bucket_logging.side_effect = None
        client.return_value.get_bucket_logging.return_value = {"LoggingEnabled": "invalid"}
        malformed = AWSService().get_s3_bucket_logging("source")

    assert failed["status"] == "unhealthy"
    assert malformed == {"service": "s3", "status": "unhealthy", "bucket": "source"}


def test_logging_endpoint_checks_ownership_and_sanitizes_provider_failure(monkeypatch):
    class StubAWS:
        owner = "tenant-a"
        fail = False

        def get_s3_bucket_tags(self, bucket):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": self.owner}}

        def get_s3_bucket_logging(self, bucket):
            if self.fail:
                return {"status": "unhealthy", "error": "private provider detail"}
            return {
                "status": "healthy", "configured": True,
                "destination_bucket": "central-logs", "destination_prefix": "archive/",
                "target_grants": [],
            }

    stub = StubAWS()
    monkeypatch.setattr(main, "aws_service", stub)
    client = TestClient(main.app)
    response = client.get("/cloud/aws/s3/buckets/source/logging")
    assert response.status_code == 200
    assert response.json()["destination_bucket"] == "central-logs"

    stub.fail = True
    response = client.get("/cloud/aws/s3/buckets/source/logging")
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "private provider detail" not in response.text

    from types import SimpleNamespace
    from fastapi import HTTPException

    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-a"))
    try:
        main.aws_s3_bucket_logging("source", request)
        assert False, "provider failure should be sanitized"
    except HTTPException as error:
        assert error.status_code == 503
        assert error.detail == "AWS resource data is unavailable"

    stub.owner = "tenant-b"
    try:
        main.aws_s3_bucket_logging("source", request)
        assert False, "foreign bucket should be hidden"
    except HTTPException as error:
        assert error.status_code == 404


def test_logging_check_is_in_bucket_analysis():
    html = TestClient(main.app).get("/console").text
    assert "['Server access logging',`${base}/logging`]" in html
