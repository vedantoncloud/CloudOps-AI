from types import SimpleNamespace
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from services.aws_service import AWSService


def test_encryption_reports_rules_and_kms_key():
    rules = [{"ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms", "KMSMasterKeyID": "key-123"
    }, "BucketKeyEnabled": True}]
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {"Rules": rules}
        }
        result = AWSService().get_s3_bucket_encryption("archive")

    client.return_value.get_bucket_encryption.assert_called_once_with(Bucket="archive")
    assert result["status"] == "healthy"
    assert result["configured"] is True
    assert result["rule_count"] == 1
    assert result["rules"] == rules


def test_encryption_absent_configuration_is_a_successful_unconfigured_state():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_encryption.side_effect = ClientError(
            {"Error": {"Code": "ServerSideEncryptionConfigurationNotFoundError"}},
            "GetBucketEncryption",
        )
        result = AWSService().get_s3_bucket_encryption("archive")

    assert result["status"] == "healthy"
    assert result["configured"] is False
    assert result["rules"] == []


def test_encryption_provider_failure_and_malformed_rules_fail_closed():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_encryption.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private details"}},
            "GetBucketEncryption",
        )
        failed = AWSService().get_s3_bucket_encryption("archive")
        client.return_value.get_bucket_encryption.side_effect = None
        client.return_value.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {"Rules": [
                {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": None}}
            ]}
        }
        malformed = AWSService().get_s3_bucket_encryption("archive")

    assert failed["status"] == "unhealthy"
    assert malformed == {"service": "s3", "status": "unhealthy", "bucket": "archive"}


def test_encryption_endpoint_scopes_tenant_and_sanitizes_provider_error(monkeypatch):
    class StubAWS:
        owner = "tenant-a"
        fail = False

        def get_s3_bucket_tags(self, bucket):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": self.owner}}

        def get_s3_bucket_encryption(self, bucket):
            if self.fail:
                return {"status": "unhealthy", "error": "private provider detail"}
            return {"status": "healthy", "configured": True, "rule_count": 1,
                    "rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}

    stub = StubAWS()
    monkeypatch.setattr(main, "aws_service", stub)
    client = TestClient(main.app)
    assert client.get("/cloud/aws/s3/buckets/archive/encryption").status_code == 200

    stub.fail = True
    response = client.get("/cloud/aws/s3/buckets/archive/encryption")
    assert response.status_code == 503
    assert "private provider detail" not in response.text

    stub.owner = "tenant-b"
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-a"))
    try:
        main.aws_s3_bucket_encryption("archive", request)
        assert False, "foreign buckets must be hidden"
    except HTTPException as error:
        assert error.status_code == 404
        assert error.detail == "S3 bucket not found"


def test_console_bucket_analysis_includes_default_encryption_check():
    html = TestClient(main.app).get("/console").text
    assert "['Default encryption',`${base}/encryption`]" in html
