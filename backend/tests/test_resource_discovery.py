from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import DiscoveredResource, ResourceDiscovery


def make_registry(provider_name="aws"):
    provider = Mock()
    provider.provider_name = provider_name
    registry = ProviderRegistry()
    registry.register(provider)
    return registry, provider


def test_discovers_ec2_resources():
    registry, provider = make_registry()
    provider.get_ec2_instances.return_value = {
        "instances": [
            {
                "instance_id": "i-123",
                "instance_state": "running",
                "instance_type": "t3.medium",
            }
        ]
    }

    resources = ResourceDiscovery(registry).list_resources("aws", "ec2")

    assert len(resources) == 1
    assert isinstance(resources[0], DiscoveredResource)
    assert resources[0].resource_id == "i-123"
    assert resources[0].provider == "aws"
    assert resources[0].resource_type == "ec2"
    assert resources[0].read_only is True
    assert resources[0].attributes["instance_state"] == "running"


def test_discovers_s3_resources():
    registry, provider = make_registry()
    provider.get_s3_buckets.return_value = {
        "buckets": [{"bucket_name": "cloudops-test", "region": "ap-south-1"}]
    }

    resources = ResourceDiscovery(registry).list_resources("aws", "s3")

    assert len(resources) == 1
    assert resources[0].resource_id == "cloudops-test"
    assert resources[0].attributes["region"] == "ap-south-1"
    assert resources[0].read_only is True


def test_calls_provider_ec2_surface():
    registry, provider = make_registry()
    provider.get_ec2_instances.return_value = {"instances": []}

    ResourceDiscovery(registry).list_resources("aws", "ec2")

    provider.get_ec2_instances.assert_called_once_with()


def test_calls_provider_s3_surface():
    registry, provider = make_registry()
    provider.get_s3_buckets.return_value = {"buckets": []}

    ResourceDiscovery(registry).list_resources("aws", "s3")

    provider.get_s3_buckets.assert_called_once_with()


def test_unknown_provider_is_rejected():
    registry, _ = make_registry()

    with pytest.raises(KeyError):
        ResourceDiscovery(registry).list_resources("azure", "ec2")


def test_unsupported_resource_type_is_rejected():
    registry, _ = make_registry()

    with pytest.raises(ValueError, match="unsupported resource type"):
        ResourceDiscovery(registry).list_resources("aws", "lambda")


def test_empty_provider_is_rejected():
    registry, _ = make_registry()

    with pytest.raises(ValueError, match="provider cannot be empty"):
        ResourceDiscovery(registry).list_resources("", "ec2")


def test_empty_resource_type_is_rejected():
    registry, _ = make_registry()

    with pytest.raises(ValueError, match="resource_type cannot be empty"):
        ResourceDiscovery(registry).list_resources("aws", "")


def test_resource_without_identifier_is_skipped():
    registry, provider = make_registry()
    provider.get_ec2_instances.return_value = {
        "instances": [{"instance_state": "running"}]
    }

    assert ResourceDiscovery(registry).list_resources("aws", "ec2") == []


def test_list_response_is_supported_as_provider_surface():
    registry, provider = make_registry()
    provider.get_ec2_instances.return_value = [
        {"instance_id": "i-456", "state": "running"}
    ]

    resources = ResourceDiscovery(registry).list_resources("aws", "ec2")

    assert len(resources) == 1
    assert resources[0].resource_id == "i-456"


def test_resource_attributes_are_preserved():
    registry, provider = make_registry()
    provider.get_ec2_instances.return_value = {
        "instances": [{"instance_id": "i-789", "state": "running"}]
    }

    resource = ResourceDiscovery(registry).list_resources("aws", "ec2")[0]

    assert resource.attributes == {"instance_id": "i-789", "state": "running"}
    assert resource.read_only is True
