import pytest

from autonomy.aws_provider import AWSProvider
from autonomy.provider_registry import ProviderRegistry


def test_register_and_get_provider():
    registry = ProviderRegistry()
    provider = AWSProvider()

    registry.register(provider)

    assert registry.get("aws") is provider
    assert registry.get("AWS") is provider


def test_provider_registry_lists_registered_providers():
    registry = ProviderRegistry()

    registry.register(AWSProvider())

    assert registry.list_providers() == ["aws"]


def test_duplicate_provider_registration_is_rejected():
    registry = ProviderRegistry()

    registry.register(AWSProvider())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(AWSProvider())


def test_unknown_provider_is_rejected():
    registry = ProviderRegistry()

    with pytest.raises(KeyError, match="unknown cloud provider"):
        registry.get("azure")


def test_provider_can_be_unregistered():
    registry = ProviderRegistry()
    provider = AWSProvider()

    registry.register(provider)

    removed = registry.unregister("AWS")

    assert removed is provider
    assert registry.has("aws") is False


def test_empty_provider_name_is_rejected():
    registry = ProviderRegistry()

    with pytest.raises(ValueError, match="provider name"):
        registry.get("")


def test_aws_provider_is_read_only_foundation():
    provider = AWSProvider()

    result = provider.get_resource(
        resource_type="ec2",
        resource_id="i-test-123",
    )

    assert result["provider"] == "aws"
    assert result["resource_type"] == "ec2"
    assert result["resource_id"] == "i-test-123"
