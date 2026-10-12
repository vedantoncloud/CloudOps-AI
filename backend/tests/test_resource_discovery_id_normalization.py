from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_id"),
    [
        (
            "ec2",
            {"instances": [{"instance_id": "  i-12345  "}]},
            "i-12345",
        ),
        (
            "s3",
            {"buckets": [{"bucket_name": "  cloudops-bucket  "}]},
            "cloudops-bucket",
        ),
    ],
)
def test_resource_discovery_strips_identifier_whitespace(
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
    assert resources[0].read_only is True


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_id"),
    [
        (
            "ec2",
            [{"id": "  i-fallback-123  "}],
            "i-fallback-123",
        ),
        (
            "s3",
            [{"name": "  fallback-bucket  "}],
            "fallback-bucket",
        ),
    ],
)
def test_resource_discovery_normalizes_fallback_identifiers(
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