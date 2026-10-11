from unittest.mock import Mock

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


def test_duplicate_resource_ids_preserve_each_record_and_attributes():
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = {
        "instances": [
            {"instance_id": "i-duplicate", "state": "running"},
            {"instance_id": "i-duplicate", "state": "stopped"},
        ]
    }

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources("aws", "ec2")

    assert len(resources) == 2
    assert [item.resource_id for item in resources] == [
        "i-duplicate",
        "i-duplicate",
    ]
    assert [item.attributes["state"] for item in resources] == [
        "running",
        "stopped",
    ]
    assert all(item.read_only is True for item in resources)
