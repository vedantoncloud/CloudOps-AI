from types import SimpleNamespace

import pytest

from autonomy.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        " ",
        "   ",
        "\t\n",
    ],
)
@pytest.mark.parametrize(
    "operation",
    [
        "get",
        "has",
        "unregister",
    ],
)
def test_registry_rejects_empty_or_whitespace_names(
    invalid_name,
    operation,
):
    registry = ProviderRegistry()

    method = getattr(registry, operation)

    with pytest.raises(
        ValueError,
        match="^provider name cannot be empty$",
    ):
        method(invalid_name)


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        " ",
        "   ",
        "\t\n",
    ],
)
def test_registry_rejects_provider_with_empty_name(invalid_name):
    registry = ProviderRegistry()
    provider = SimpleNamespace(provider_name=invalid_name)

    with pytest.raises(
        ValueError,
        match="^provider name cannot be empty$",
    ):
        registry.register(provider)

    assert registry.list_providers() == []
@pytest.mark.parametrize(
    "invalid_name",
    [
        None,
        123,
        [],
        {},
    ],
)
@pytest.mark.parametrize(
    "operation",
    [
        "get",
        "has",
        "unregister",
    ],
)
def test_registry_rejects_non_string_names(
    invalid_name,
    operation,
):
    registry = ProviderRegistry()

    method = getattr(registry, operation)

    with pytest.raises(
        ValueError,
        match="^provider name cannot be empty$",
    ):
        method(invalid_name)


@pytest.mark.parametrize(
    "invalid_name",
    [
        None,
        123,
        [],
        {},
    ],
)
def test_registry_rejects_provider_with_non_string_name(invalid_name):
    registry = ProviderRegistry()
    provider = SimpleNamespace(provider_name=invalid_name)

    with pytest.raises(
        ValueError,
        match="^provider name cannot be empty$",
    ):
        registry.register(provider)

    assert registry.list_providers() == []