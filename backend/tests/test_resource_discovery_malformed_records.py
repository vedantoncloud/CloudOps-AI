from unittest.mock import Mock

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


def test_malformed_ec2_records_are_skipped_without_losing_valid_records():
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = {
        "instances": [
            None,
            "invalid-record",
            42,
            {"state": "running"},
            {"instance_id": "i-valid", "state": "running"},
        ]
    }

    registry = ProviderRegistry()
    registry.register(provider)

    resources = ResourceDiscovery(registry).list_resources("aws", "ec2")

    assert len(resources) == 1
    assert resources[0].resource_id == "i-valid"
    assert resources[0].attributes == {
        "instance_id": "i-valid",
        "state": "running",
    }
    assert resources[0].read_only is True
