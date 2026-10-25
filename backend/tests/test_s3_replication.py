from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import main
from services.aws_service import AWSService


def test_replication_reports_rules_and_enabled_count():
    rules = [
        {"ID": "to-backup", "Status": "Enabled", "Destination": {"Bucket": "arn:aws:s3:::backup"}},
        {"ID": "paused", "Status": "Disabled", "Destination": {"Bucket": "arn:aws:s3:::old"}},
    ]
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_replication.return_value = {
            "ReplicationConfiguration": {"Role": "arn:aws:iam::123:role/replication", "Rules": rules}
        }
        result = AWSService().get_s3_bucket_replication("source")

    client.return_value.get_bucket_replication.assert_called_once_with(Bucket="source")
    assert result["configured"] is True
    assert result["rule_count"] == 2
    assert result["enabled_rule_count"] == 1
    assert result["rules"] == rules


def test_replication_missing_configuration_is_a_successful_empty_state():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_replication.side_effect = ClientError(
            {"Error": {"Code": "ReplicationConfigurationNotFoundError", "Message": "none"}},
            "GetBucketReplication",
        )
        result = AWSService().get_s3_bucket_replication("source")

    assert result["status"] == "healthy"
    assert result["configured"] is False
    assert result["enabled_rule_count"] == 0
    assert result["rules"] == []


def test_replication_provider_errors_and_malformed_rules_fail_closed():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_replication.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private detail"}},
            "GetBucketReplication",
        )
        failed = AWSService().get_s3_bucket_replication("source")
        client.return_value.get_bucket_replication.side_effect = None
        client.return_value.get_bucket_replication.return_value = {
            "ReplicationConfiguration": {"Rules": "invalid"}
        }
        malformed = AWSService().get_s3_bucket_replication("source")

    assert failed["status"] == "unhealthy"
    assert malformed == {"service": "s3", "status": "unhealthy", "bucket": "source"}


def test_replication_endpoint_enforces_tenant_ownership_and_sanitizes_failure(monkeypatch):
    class StubAWS:
        tenant = "tenant-a"

        def get_s3_bucket_tags(self, bucket_name):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": self.tenant}}

        def get_s3_bucket_replication(self, bucket_name):
            return {"status": "unhealthy", "error": "private AWS detail"}

    stub = StubAWS()
    monkeypatch.setattr(main, "aws_service", stub)
    # The application is in development mode here; exercise route-level tenant checks directly.
    from types import SimpleNamespace
    from fastapi import HTTPException

    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-a"))
    try:
        main.aws_s3_bucket_replication("source", request)
        assert False, "provider failure should be sanitized"
    except HTTPException as error:
        assert error.status_code == 503
        assert error.detail == "AWS resource data is unavailable"

    stub.tenant = "tenant-b"
    try:
        main.aws_s3_bucket_replication("source", request)
        assert False, "foreign bucket should be hidden"
    except HTTPException as error:
        assert error.status_code == 404


def test_replication_endpoint_and_console_report_expose_configuration(monkeypatch):
    class StubAWS:
        def get_s3_bucket_tags(self, bucket_name):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": "local"}}

        def get_s3_bucket_replication(self, bucket_name):
            return {"status": "healthy", "configured": True, "rule_count": 1, "enabled_rule_count": 1, "rules": [{"ID": "replicate", "Status": "Enabled"}]}

    monkeypatch.setattr(main, "aws_service", StubAWS())
    response = TestClient(main.app).get("/cloud/aws/s3/buckets/source/replication")
    assert response.status_code == 200
    assert response.json()["enabled_rule_count"] == 1
    html = TestClient(main.app).get("/console").text
    assert "['Replication',`${base}/replication`]" in html
