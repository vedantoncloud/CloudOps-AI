from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_id"),
    [
        (
            "ec2",
            {
                "instances": [{
                    "resource_id": "resource-123",
                    "id": "generic-123",
                    "instance_id": "i-canonical-123",
                    "InstanceId": "i-uppercase-123",
                }]
            },
            "resource-123",
        ),
        (
            "s3",
            {
                "buckets": [{
                    "resource_id": "resource-456",
                    "id": "generic-456",
                    "bucket_name": "canonical-bucket",
                    "name": "fallback-bucket",
                }]
            },
            "resource-456",
        ),
    ],
)
def test_resource_discovery_prefers_highest_priority_identifier(
    resource_type,
    response,
    expected_id,
):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = response
    provider.get_s3_buckets.return_value = response

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        resource_type,
    )

    assert len(resources) == 1
    assert resources[0].resource_id == expected_id


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_id"),
    [
        (
            "ec2",
            {
                "instances": [{
                    "resource_id": "   ",
                    "id": "generic-ec2",
                    "instance_id": "i-ec2-fallback",
                }]
            },
            "generic-ec2",
        ),
        (
            "s3",
            {
                "buckets": [{
                    "resource_id": "",
                    "id": "generic-s3",
                    "bucket_name": "canonical-bucket",
                }]
            },
            "generic-s3",
        ),
    ],
)
def test_resource_discovery_uses_next_identifier_when_primary_is_empty(
    resource_type,
    response,
    expected_id,
):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = response
    provider.get_s3_buckets.return_value = response

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        resource_type,
    )

    assert len(resources) == 1
    assert resources[0].resource_id == expected_id


@pytest.mark.parametrize(
    ("resource_type", "response"),
    [
        ("ec2", {"instances": [{"resource_id": " ", "id": ""}]}),
        ("s3", {"buckets": [{"resource_id": "", "name": "  "}]}),
    ],
)
def test_resource_discovery_skips_items_with_only_empty_identifiers(
    resource_type,
    response,
):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = response
    provider.get_s3_buckets.return_value = response

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        resource_type,
    )

    assert resources == []