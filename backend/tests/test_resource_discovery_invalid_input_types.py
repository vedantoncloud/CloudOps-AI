import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    "invalid_provider",
    [
        None,
        123,
        [],
        {},
    ],
)
def test_discovery_rejects_non_string_provider(invalid_provider):
    discovery = ResourceDiscovery(ProviderRegistry())

    with pytest.raises(ValueError, match="^provider cannot be empty$"):
        discovery.list_resources(
            provider=invalid_provider,
            resource_type="ec2",
        )


@pytest.mark.parametrize(
    "invalid_resource_type",
    [
        None,
        123,
        [],
        {},
    ],
)
def test_discovery_rejects_non_string_resource_type(invalid_resource_type):
    discovery = ResourceDiscovery(ProviderRegistry())

    with pytest.raises(
        ValueError,
        match="^resource_type cannot be empty$",
    ):
        discovery.list_resources(
            provider="aws",
            resource_type=invalid_resource_type,
        )