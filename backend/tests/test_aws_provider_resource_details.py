from unittest.mock import Mock

import pytest

from autonomy.aws_provider import AWSProvider


def make_provider():
    service = Mock()
    return AWSProvider(service), service


def test_ec2_resource_details():
    provider, service = make_provider()
    instance = {"instance_id": "i-12345678", "state": "running"}
    service.get_ec2_instance.return_value = {
        "status": "healthy",
        "instance": instance,
    }

    result = provider.get_resource("ec2", "i-12345678")

    assert result["status"] == "healthy"
    assert result["attributes"] == instance
    assert result["resource_type"] == "ec2"
    assert result["read_only"] is True
    service.get_ec2_instance.assert_called_once_with("i-12345678")
    service.get_ec2_instances.assert_not_called()


def test_missing_ec2_resource_preserves_generic_observation():
    provider, service = make_provider()
    service.get_ec2_instance.return_value = {
        "status": "healthy",
        "instance": None,
    }

    result = provider.get_resource("ec2", "i-missing")

    assert result == {
        "provider": "aws",
        "resource_type": "ec2",
        "resource_id": "i-missing",
        "read_only": True,
    }


def test_s3_resource_details():
    provider, service = make_provider()
    service.get_s3_bucket_details.return_value = {
        "status": "healthy",
        "bucket": "demo-bucket",
        "region": "ap-south-1",
    }

    result = provider.get_resource("s3", "demo-bucket")

    assert result["status"] == "healthy"
    assert result["attributes"]["region"] == "ap-south-1"
    assert result["read_only"] is True


def test_s3_resource_error():
    provider, service = make_provider()
    service.get_s3_bucket_details.return_value = {
        "status": "unhealthy",
        "bucket": "demo-bucket",
        "error": "AccessDenied",
    }

    result = provider.get_resource("s3", "demo-bucket")

    assert result["status"] == "unhealthy"
    assert result["error"] == "AccessDenied"


def test_unsupported_type_preserves_generic_observation():
    provider, service = make_provider()

    result = provider.get_resource("service", "svc-audit")

    assert result == {
        "provider": "aws",
        "resource_type": "service",
        "resource_id": "svc-audit",
        "read_only": True,
    }
    service.get_ec2_instances.assert_not_called()
    service.get_s3_bucket_details.assert_not_called()


def test_ec2_inventory_error():
    provider, service = make_provider()
    service.get_ec2_instance.return_value = {
        "status": "unhealthy",
        "error": "AWS unavailable",
    }

    result = provider.get_resource("ec2", "i-12345678")

    assert result["status"] == "unhealthy"
    assert result["read_only"] is True
    assert result["error"] == "AWS unavailable"


def test_ec2_resource_details_propagates_missing_instance_payload_as_generic():
    provider, service = make_provider()
    service.get_ec2_instance.return_value = {"status": "healthy"}

    result = provider.get_resource("ec2", "i-missing")

    assert result["resource_id"] == "i-missing"
    assert result["read_only"] is True
    assert "attributes" not in result


def test_malformed_ec2_id_does_not_call_aws():
    provider, service = make_provider()

    result = provider.get_resource("ec2", "i-test-123")

    assert result["resource_id"] == "i-test-123"
    assert result["read_only"] is True
    assert "status" not in result
    service.get_ec2_instance.assert_not_called()
