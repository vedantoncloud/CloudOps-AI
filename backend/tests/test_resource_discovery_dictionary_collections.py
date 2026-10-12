from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    ("resource_type", "response", "expected_ids", "method_name"),
    [
        (
            "ec2",
            {
                "instances": {
                    "first": {
                        "instance_id": "i-101",
                        "state": "running",
                    },
                    "second": {
                        "instance_id": "i-102",
                        "state": "stopped",
                    },
                }
            },
            ["i-101", "i-102"],
            "get_ec2_instances",
        ),
        (
            "s3",
            {
                "buckets": {
                    "first": {
                        "bucket_name": "cloudops-first",
                        "region": "ap-south-1",
                    },
                    "second": {
                        "bucket_name": "cloudops-second",
                        "region": "us-east-1",
                    },
                }
            },
            ["cloudops-first", "cloudops-second"],
            "get_s3_buckets",
        ),
    ],
)
def test_discovers_resources_from_dictionary_collection(
    resource_type,
    response,
    expected_ids,
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

    assert [resource.resource_id for resource in resources] == expected_ids
    assert all(resource.provider == "aws" for resource in resources)
    assert all(resource.resource_type == resource_type for resource in resources)
    assert all(resource.read_only is True for resource in resources)


@pytest.mark.parametrize(
    ("resource_type", "collection_key", "method_name"),
    [
        ("ec2", "instances", "get_ec2_instances"),
        ("s3", "buckets", "get_s3_buckets"),
    ],
)
@pytest.mark.parametrize(
    "collection",
    [
        {},
        {"first": "invalid"},
        {"first": {"state": "running"}, "second": None},
    ],
)
def test_invalid_dictionary_collections_return_empty_list(
    resource_type,
    collection_key,
    method_name,
    collection,
):
    provider = Mock()
    provider.provider_name = "aws"
    getattr(provider, method_name).return_value = {
        collection_key: collection
    }

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        resource_type,
    )

    assert resources == []


def test_list_collection_still_takes_priority_over_dictionary_collection():
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = {
        "instances": [
            {"instance_id": "i-list-101"}
        ],
        "other": {
            "instance_id": "i-other-102"
        },
    }

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )

    assert [resource.resource_id for resource in resources] == ["i-list-101"]