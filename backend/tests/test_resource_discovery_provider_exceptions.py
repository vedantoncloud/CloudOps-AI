from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    ("resource_type", "provider_method"),
    [
        ("ec2", "get_ec2_instances"),
        ("s3", "get_s3_buckets"),
    ],
)
def test_provider_exception_propagates_from_resource_discovery(
    resource_type,
    provider_method,
):
    provider = Mock()
    provider.provider_name = "aws"
    getattr(provider, provider_method).side_effect = RuntimeError(
        "provider connection failed"
    )

    registry = ProviderRegistry()
    registry.register(provider)

    discovery = ResourceDiscovery(registry)

    with pytest.raises(
        RuntimeError,
        match="provider connection failed",
    ):
        discovery.list_resources("aws", resource_type)