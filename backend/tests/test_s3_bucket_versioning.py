from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient
from types import SimpleNamespace

import main
from services.aws_service import AWSService


def test_bucket_versioning_reports_enabled_and_mfa_delete():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_versioning.return_value = {
            "Status": "Enabled", "MFADelete": "Enabled"
        }

        result = AWSService().get_s3_bucket_versioning("archive")

    client.return_value.get_bucket_versioning.assert_called_once_with(Bucket="archive")
    assert result == {
        "service": "s3", "status": "healthy", "bucket": "archive",
        "versioning": "enabled", "mfa_delete": "enabled",
    }


def test_bucket_versioning_defaults_absent_configuration_to_disabled():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_versioning.return_value = {}

        result = AWSService().get_s3_bucket_versioning("archive")

    assert result["versioning"] == "disabled"
    assert result["mfa_delete"] == "disabled"


def test_bucket_versioning_provider_errors_are_unhealthy():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_versioning.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "account details"}},
            "GetBucketVersioning",
        )

        result = AWSService().get_s3_bucket_versioning("archive")

    assert result["status"] == "unhealthy"
    assert "versioning" not in result


def test_versioning_endpoint_checks_ownership_and_sanitizes_provider_failure(monkeypatch):
    class StubAWS:
        owned = True

        def get_s3_bucket_tags(self, bucket_name):
            tenant = "tenant-a" if self.owned else "tenant-b"
            return {"status": "healthy", "tags": {"CloudOpsTenantId": tenant}}

        def get_s3_bucket_versioning(self, bucket_name):
            return {"status": "unhealthy", "error": "private account diagnostics"}

    stub = StubAWS()
    monkeypatch.setattr(main, "aws_service", stub)

    request = SimpleNamespace(state=SimpleNamespace(
        tenant_scoped=True, tenant_id="tenant-a"
    ))
    try:
        main.aws_s3_bucket_versioning("archive", request)
        assert False, "provider failures should be sanitized"
    except HTTPException as error:
        assert error.status_code == 503
        assert error.detail == "AWS resource data is unavailable"

    stub.owned = False
    try:
        main.aws_s3_bucket_versioning("archive", request)
        assert False, "foreign buckets should be hidden"
    except HTTPException as error:
        assert error.status_code == 404
        assert error.detail == "S3 bucket not found"


def test_versioning_endpoint_returns_state_for_owned_bucket(monkeypatch):
    class StubAWS:
        def get_s3_bucket_tags(self, bucket_name):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": "local"}}

        def get_s3_bucket_versioning(self, bucket_name):
            return {"status": "healthy", "bucket": bucket_name, "versioning": "suspended", "mfa_delete": "disabled"}

    monkeypatch.setattr(main, "aws_service", StubAWS())
    response = TestClient(main.app).get("/cloud/aws/s3/buckets/archive/versioning")

    assert response.status_code == 200
    assert response.json()["versioning"] == "suspended"


def test_console_bucket_analysis_includes_versioning_status():
    html = TestClient(main.app).get("/console").text

    assert "['Versioning',`${base}/versioning`]" in html
    assert "bucket configuration" in html


def test_bucket_lifecycle_reports_rules_and_enabled_count():
    rules = [
        {"ID": "archive-old", "Status": "Enabled", "Expiration": {"Days": 90}},
        {"ID": "keep-current", "Status": "Disabled", "Filter": {"Prefix": "keep/"}},
    ]
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_lifecycle_configuration.return_value = {"Rules": rules}
        result = AWSService().get_s3_bucket_lifecycle("archive")

    client.return_value.get_bucket_lifecycle_configuration.assert_called_once_with(Bucket="archive")
    assert result == {
        "service": "s3", "status": "healthy", "bucket": "archive",
        "configured": True, "rule_count": 2, "enabled_rule_count": 1, "rules": rules,
    }


def test_bucket_lifecycle_treats_missing_configuration_as_empty():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_lifecycle_configuration.side_effect = ClientError(
            {"Error": {"Code": "NoSuchLifecycleConfiguration", "Message": "none"}},
            "GetBucketLifecycleConfiguration",
        )
        result = AWSService().get_s3_bucket_lifecycle("archive")

    assert result["status"] == "healthy"
    assert result["configured"] is False
    assert result["rules"] == []


def test_bucket_lifecycle_provider_errors_are_unhealthy():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_bucket_lifecycle_configuration.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private diagnostics"}},
            "GetBucketLifecycleConfiguration",
        )
        result = AWSService().get_s3_bucket_lifecycle("archive")

    assert result["status"] == "unhealthy"
    assert "rules" not in result


def test_lifecycle_endpoint_checks_tenant_ownership_and_returns_configuration(monkeypatch):
    class StubAWS:
        def get_s3_bucket_tags(self, bucket_name):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": "local"}}

        def get_s3_bucket_lifecycle(self, bucket_name):
            return {"status": "healthy", "configured": True, "rule_count": 1, "enabled_rule_count": 1, "rules": [{"ID": "expire", "Status": "Enabled"}]}

    monkeypatch.setattr(main, "aws_service", StubAWS())
    response = TestClient(main.app).get("/cloud/aws/s3/buckets/archive/lifecycle")

    assert response.status_code == 200
    assert response.json()["rules"] == [{"ID": "expire", "Status": "Enabled"}]


def test_lifecycle_endpoint_hides_foreign_bucket_before_reading_configuration(monkeypatch):
    class StubAWS:
        def get_s3_bucket_tags(self, bucket_name):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": "tenant-b"}}

        def get_s3_bucket_lifecycle(self, bucket_name):
            raise AssertionError("foreign bucket configuration must not be read")

    monkeypatch.setattr(main, "aws_service", StubAWS())
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-a"))

    try:
        main.aws_s3_bucket_lifecycle("archive", request)
        assert False, "foreign buckets must be hidden"
    except HTTPException as error:
        assert error.status_code == 404
        assert error.detail == "S3 bucket not found"


def test_console_bucket_analysis_includes_lifecycle_rules():
    html = TestClient(main.app).get("/console").text

    assert "['Lifecycle',`${base}/lifecycle`]" in html
