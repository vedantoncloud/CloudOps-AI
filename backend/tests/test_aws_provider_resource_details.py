from unittest.mock import Mock

import pytest

from autonomy.aws_provider import AWSProvider


def make_provider():
    service = Mock()
    return AWSProvider(service), service


def test_ec2_resource_details():
    provider, service = make_provider()
    instance = {"instance_id": "i-123", "state": "running"}
    service.get_ec2_instances.return_value = {
        "status": "healthy",
        "instances": [instance],
    }

    result = provider.get_resource("ec2", "i-123")

    assert result["status"] == "healthy"
    assert result["attributes"] == instance
    assert result["read_only"] is True


def test_missing_ec2_resource():
    provider, service = make_provider()
    service.get_ec2_instances.return_value = {
        "status": "healthy",
        "instances": [],
    }

    result = provider.get_resource("ec2", "i-missing")

    assert result["status"] == "not_found"


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


def test_unsupported_resource_type():
    provider, _ = make_provider()

    with pytest.raises(ValueError, match="unsupported AWS resource type"):
        provider.get_resource("rds", "db-123")


@pytest.mark.parametrize(
    ("resource_type", "resource_id"),
    [("", "i-123"), ("ec2", ""), (" ", "i-123"), ("s3", " ")],
)
def test_empty_resource_inputs(resource_type, resource_id):
    provider, _ = make_provider()

    with pytest.raises(ValueError):
        provider.get_resource(resource_type, resource_id)


def test_ec2_inventory_error():
    provider, service = make_provider()
    service.get_ec2_instances.return_value = {
        "status": "unhealthy",
        "error": "AWS unavailable",
    }

    result = provider.get_resource("ec2", "i-123")

    assert result["status"] == "unhealthy"
    assert result["read_only"] is True
