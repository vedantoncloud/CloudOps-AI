from types import SimpleNamespace

import pytest

from autonomy.provider_registry import ProviderRegistry


def make_provider(name):
    return SimpleNamespace(provider_name=name)


def test_registry_normalizes_provider_name_during_registration():
    registry = ProviderRegistry()
    provider = make_provider(" AWS ")

    registry.register(provider)

    assert registry.list_providers() == ["aws"]
    assert registry.has("aws") is True
    assert registry.has(" AWS ") is True
    assert registry.get("Aws") is provider


def test_registry_rejects_duplicate_normalized_provider_names():
    registry = ProviderRegistry()

    first_provider = make_provider("AWS")
    second_provider = make_provider(" aws ")

    registry.register(first_provider)

    with pytest.raises(
        ValueError,
        match="provider already registered: aws",
    ):
        registry.register(second_provider)

    assert registry.list_providers() == ["aws"]
    assert registry.get("aws") is first_provider


def test_registry_unregister_normalizes_provider_name():
    registry = ProviderRegistry()
    provider = make_provider(" AWS ")

    registry.register(provider)

    removed = registry.unregister("  AwS  ")

    assert removed is provider
    assert registry.list_providers() == []
    assert registry.has("aws") is False


@pytest.mark.parametrize(
    "lookup_name",
    [
        "aws",
        "AWS",
        " Aws ",
        "  AWS  ",
    ],
)
def test_registry_get_supports_normalized_name_variants(lookup_name):
    registry = ProviderRegistry()
    provider = make_provider("aws")

    registry.register(provider)

    assert registry.get(lookup_name) is provider