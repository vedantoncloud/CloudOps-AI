from types import SimpleNamespace

import pytest

from autonomy.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    "invalid_provider",
    [
        None,
        object(),
        SimpleNamespace(),
    ],
)
def test_register_rejects_objects_without_valid_provider_name(
    invalid_provider,
):
    registry = ProviderRegistry()

    with pytest.raises(
        ValueError,
        match="^provider name cannot be empty$",
    ):
        registry.register(invalid_provider)

    assert registry.list_providers() == []


def test_register_accepts_provider_with_valid_name():
    registry = ProviderRegistry()
    provider = SimpleNamespace(provider_name="aws")

    result = registry.register(provider)

    assert result is provider
    assert registry.get("aws") is provider
    assert registry.list_providers() == ["aws"]


def test_invalid_registration_does_not_affect_existing_provider():
    registry = ProviderRegistry()
    existing_provider = SimpleNamespace(provider_name="aws")

    registry.register(existing_provider)

    with pytest.raises(
        ValueError,
        match="^provider name cannot be empty$",
    ):
        registry.register(None)

    assert registry.get("aws") is existing_provider
    assert registry.list_providers() == ["aws"]