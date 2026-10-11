from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    ("resource_type", "response", "method_name", "expected_ids"),
    [
        (
            "ec2",
            {
                "production": {
                    "instance_id": "i-map-prod",
                    "state": "running",
                },
                "development": {
                    "instance_id": "i-map-dev",
                    "state": "stopped",
                },
            },
            "get_ec2_instances",
            ["i-map-prod", "i-map-dev"],
        ),
        (
            "s3",
            {
                "logs": {
                    "bucket_name": "cloudops-logs",
                    "region": "ap-south-1",
                },
                "backups": {
                    "bucket_name": "cloudops-backups",
                    "region": "ap-south-1",
                },
            },
            "get_s3_buckets",
            ["cloudops-logs", "cloudops-backups"],
        ),
    ],
)
def test_mapping_style_provider_response_discovers_resources(
    resource_type,
    response,
    method_name,
    expected_ids,
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

    if resource_type == "ec2":
        assert resources[0].attributes["state"] == "running"
        assert resources[1].attributes["state"] == "stopped"
    else:
        assert resources[0].attributes["region"] == "ap-south-1"
        assert resources[1].attributes["region"] == "ap-south-1"