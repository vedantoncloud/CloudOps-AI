from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


@pytest.mark.parametrize(
    ("provider_input", "resource_type_input", "expected_provider", "expected_type"),
    [
        ("AWS", "EC2", "aws", "ec2"),
        (" AWS ", " EC2 ", "aws", "ec2"),
        ("Aws", "Ec2", "aws", "ec2"),
        ("AWS", "S3", "aws", "s3"),
        (" AWS ", " S3 ", "aws", "s3"),
    ],
)
def test_discovery_normalizes_provider_and_resource_type_inputs(
    provider_input,
    resource_type_input,
    expected_provider,
    expected_type,
):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = {
        "instances": [
            {
                "instance_id": "i-normalization-001",
                "state": "running",
            }
        ]
    }
    provider.get_s3_buckets.return_value = {
        "buckets": [
            {
                "bucket_name": "normalization-bucket",
                "region": "ap-south-1",
            }
        ]
    }

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources(
        provider=provider_input,
        resource_type=resource_type_input,
    )

    assert len(resources) == 1
    assert resources[0].provider == expected_provider
    assert resources[0].resource_type == expected_type
    assert resources[0].read_only is True

    if expected_type == "ec2":
        assert resources[0].resource_id == "i-normalization-001"
        provider.get_ec2_instances.assert_called_once_with()
        provider.get_s3_buckets.assert_not_called()
    else:
        assert resources[0].resource_id == "normalization-bucket"
        provider.get_s3_buckets.assert_called_once_with()
        provider.get_ec2_instances.assert_not_called()