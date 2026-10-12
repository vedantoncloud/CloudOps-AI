from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_id", "method_name"),
    [
        (
            "ec2",
            {
                "instance_id": "i-single-123",
                "state": "running",
                "instance_type": "t3.medium",
            },
            "i-single-123",
            "get_ec2_instances",
        ),
        (
            "s3",
            {
                "bucket_name": "single-cloudops-bucket",
                "region": "ap-south-1",
            },
            "single-cloudops-bucket",
            "get_s3_buckets",
        ),
    ],
)
def test_discovers_single_resource_mapping(
    resource_type,
    response,
    expected_id,
    method_name,
):
    provider = Mock()
    provider.provider_name = "aws"
    getattr(provider, method_name).return_value = response

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        resource_type,
    )

    assert len(resources) == 1
    assert resources[0].resource_id == expected_id
    assert resources[0].provider == "aws"
    assert resources[0].resource_type == resource_type
    assert resources[0].attributes == response
    assert resources[0].read_only is True


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_id"),
    [
        (
            "ec2",
            {"id": "i-single-fallback", "state": "running"},
            "i-single-fallback",
        ),
        (
            "s3",
            {"name": "single-fallback-bucket", "region": "ap-south-1"},
            "single-fallback-bucket",
        ),
    ],
)
def test_discovers_single_mapping_using_fallback_identifier(
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
    "response",
    [
        {"unexpected": "shape"},
        {},
        {"metadata": {"region": "ap-south-1"}},
    ],
)
def test_unknown_single_mapping_shapes_are_ignored(response):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = response

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )

    assert resources == []