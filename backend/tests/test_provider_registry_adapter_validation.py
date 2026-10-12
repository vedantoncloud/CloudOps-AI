from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry


def make_provider():
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances = Mock()
    provider.get_ec2_summary = Mock()
    provider.get_s3_buckets = Mock()
    return provider


@pytest.mark.parametrize(
    "method_name",
    [
        "get_ec2_instances",
        "get_ec2_summary",
        "get_s3_buckets",
    ],
)
def test_registration_rejects_missing_provider_methods(method_name):
    provider = make_provider()
    delattr(provider, method_name)

    registry = ProviderRegistry()

    with pytest.raises(
        ValueError,
        match=f"provider must implement callable {method_name}",
    ):
        registry.register(provider)


@pytest.mark.parametrize(
    "method_name",
    [
        "get_ec2_instances",
        "get_ec2_summary",
        "get_s3_buckets",
    ],
)
def test_registration_rejects_non_callable_provider_methods(method_name):
    provider = make_provider()
    setattr(provider, method_name, None)

    registry = ProviderRegistry()

    with pytest.raises(
        ValueError,
        match=f"provider must implement callable {method_name}",
    ):
        registry.register(provider)


def test_registration_accepts_complete_provider_adapter():
    provider = make_provider()
    registry = ProviderRegistry()

    registered = registry.register(provider)

    assert registered is provider
    assert registry.has("aws")
    assert registry.get("aws") is provider


def test_invalid_provider_is_not_added_to_registry():
    provider = make_provider()
    provider.get_s3_buckets = None

    registry = ProviderRegistry()

    with pytest.raises(ValueError):
        registry.register(provider)

    assert registry.list_providers() == []


def test_provider_methods_are_not_called_during_validation():
    provider = make_provider()
    registry = ProviderRegistry()

    registry.register(provider)

    provider.get_ec2_instances.assert_not_called()
    provider.get_ec2_summary.assert_not_called()
    provider.get_s3_buckets.assert_not_called()