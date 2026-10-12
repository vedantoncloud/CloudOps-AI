from unittest.mock import Mock

import pytest

from autonomy.aws_provider import AWSProvider
from autonomy.provider_registry import ProviderRegistry


def test_aws_provider_exposes_expected_read_only_capabilities():
    provider = AWSProvider(service=Mock())

    assert provider.get_capabilities() == [
        "compute.instances.list",
        "compute.instances.summary",
        "resources.get",
        "storage.buckets.list",
    ]


def test_registry_returns_normalized_provider_capabilities():
    registry = ProviderRegistry()
    registry.register(AWSProvider(service=Mock()))

    result = registry.get_capabilities(" AWS ")

    assert result == {
        "provider": "aws",
        "capabilities": [
            "compute.instances.list",
            "compute.instances.summary",
            "resources.get",
            "storage.buckets.list",
        ],
    }


def test_registry_sorts_and_deduplicates_capabilities():
    class CapabilityProvider:
        provider_name = "custom"

        def get_capabilities(self):
            return ["z.read", "a.read", "z.read", " a.read "]

    registry = ProviderRegistry()
    registry.register(CapabilityProvider())

    assert registry.get_capabilities("custom") == {
        "provider": "custom",
        "capabilities": ["a.read", "z.read"],
    }


def test_registry_rejects_provider_without_capability_discovery():
    class BasicProvider:
        provider_name = "basic"

    registry = ProviderRegistry()
    registry.register(BasicProvider())

    with pytest.raises(ValueError, match="does not expose capability discovery"):
        registry.get_capabilities("basic")


@pytest.mark.parametrize(
    "capabilities",
    [
        None,
        "compute.instances.list",
        ["valid.read", ""],
        ["valid.read", None],
        [123],
    ],
)
def test_registry_rejects_invalid_capability_responses(capabilities):
    class InvalidCapabilityProvider:
        provider_name = "invalid"

        def get_capabilities(self):
            return capabilities

    registry = ProviderRegistry()
    registry.register(InvalidCapabilityProvider())

    with pytest.raises(ValueError):
        registry.get_capabilities("invalid")


def test_registry_rejects_unknown_provider():
    registry = ProviderRegistry()

    with pytest.raises(KeyError, match="unknown cloud provider"):
        registry.get_capabilities("missing")
