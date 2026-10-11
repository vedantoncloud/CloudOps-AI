from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    "identifier_key",
    ["resource_id", "id", "instance_id", "InstanceId"],
)
def test_ec2_identifier_aliases_are_supported(identifier_key):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = {
        "instances": [{identifier_key: "i-alias-123"}]
    }

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources("aws", "ec2")

    assert len(resources) == 1
    assert resources[0].resource_id == "i-alias-123"


@pytest.mark.parametrize(
    "identifier_key",
    ["resource_id", "id", "bucket_name", "name", "Name"],
)
def test_s3_identifier_aliases_are_supported(identifier_key):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_s3_buckets.return_value = {
        "buckets": [{identifier_key: "bucket-alias-123"}]
    }

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources("aws", "s3")

    assert len(resources) == 1
    assert resources[0].resource_id == "bucket-alias-123"


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_id"),
    [
        (
            "ec2",
            {
                "instances": [
                    {
                        "resource_id": "preferred-ec2",
                        "id": "secondary-ec2",
                        "instance_id": "third-ec2",
                    }
                ]
            },
            "preferred-ec2",
        ),
        (
            "s3",
            {
                "buckets": [
                    {
                        "resource_id": "preferred-s3",
                        "id": "secondary-s3",
                        "bucket_name": "third-s3",
                    }
                ]
            },
            "preferred-s3",
        ),
    ],
)
def test_resource_identifier_priority_is_preserved(
    resource_type,
    response,
    expected_id,
):
    provider = Mock()
    provider.provider_name = "aws"

    if resource_type == "ec2":
        provider.get_ec2_instances.return_value = response
    else:
        provider.get_s3_buckets.return_value = response

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        resource_type,
    )

    assert len(resources) == 1
    assert resources[0].resource_id == expected_id