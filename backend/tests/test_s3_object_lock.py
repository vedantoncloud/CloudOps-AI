from types import SimpleNamespace
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import main
from services.aws_service import AWSService


def test_object_lock_returns_default_retention_configuration():
    configuration = {"ObjectLockEnabled": "Enabled", "Rule": {
        "DefaultRetention": {"Mode": "COMPLIANCE", "Days": 30}
    }}
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_object_lock_configuration.return_value = {
            "ObjectLockConfiguration": configuration
        }
        result = AWSService().get_s3_bucket_object_lock("archive")
    client.return_value.get_object_lock_configuration.assert_called_once_with(Bucket="archive")
    assert result == {"service": "s3", "status": "healthy", "bucket": "archive",
                      "enabled": True, "default_retention": configuration["Rule"]}


def test_object_lock_absent_configuration_is_explicitly_unconfigured():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.get_object_lock_configuration.side_effect = ClientError(
            {"Error": {"Code": "ObjectLockConfigurationNotFoundError"}},
            "GetObjectLockConfiguration",
        )
        result = AWSService().get_s3_bucket_object_lock("archive")
    assert result["status"] == "healthy"
    assert result["enabled"] is False
    assert result["default_retention"] is None


def test_object_lock_malformed_retention_and_provider_errors_fail_closed():
    with patch("services.aws_service.boto3.client") as client:
        call = client.return_value.get_object_lock_configuration
        call.return_value = {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled", "Rule": {
            "DefaultRetention": {"Mode": "COMPLIANCE", "Days": 0}
        }}}
        malformed = AWSService().get_s3_bucket_object_lock("archive")
        call.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "secret"}},
                                       "GetObjectLockConfiguration")
        failed = AWSService().get_s3_bucket_object_lock("archive")
    assert malformed["status"] == "unhealthy"
    assert failed["status"] == "unhealthy"


def test_object_lock_endpoint_enforces_tenant_scope_and_sanitizes_errors(monkeypatch):
    class StubAWS:
        def get_s3_bucket_tags(self, bucket):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": "tenant-a"}}

        def get_s3_bucket_object_lock(self, bucket):
            return {"service": "s3", "status": "unhealthy", "bucket": bucket,
                    "error": "private provider details"}

    monkeypatch.setattr(main, "aws_service", StubAWS())
    client = TestClient(main.app)
    response = client.get("/cloud/aws/s3/buckets/archive/object-lock")
    assert response.status_code == 503
    assert "private provider details" not in response.text
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-b"))
    try:
        main.aws_s3_bucket_object_lock("archive", request)
        assert False, "foreign buckets must remain hidden"
    except Exception as error:
        assert getattr(error, "status_code", None) == 404


def test_object_lock_contract_rejects_invalid_shapes_and_console_exposes_check():
    malformed = {"service": "s3", "status": "healthy", "bucket": "archive",
                 "enabled": True, "default_retention": {"DefaultRetention": {"Mode": "INVALID"}}}
    try:
        main._validate_s3_bucket_contract(malformed, "archive", "object-lock")
        assert False, "invalid retention mode must fail closed"
    except Exception as error:
        assert getattr(error, "status_code", None) == 503
    html = TestClient(main.app).get("/console").text
    assert "Object Lock retention" in html
    assert "/object-lock" in html
