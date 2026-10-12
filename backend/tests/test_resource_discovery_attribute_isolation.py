from unittest.mock import Mock

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


def make_registry(response):
    provider = Mock()
    provider.provider_name = "aws"
    provider.get_ec2_instances.return_value = {
        "instances": [response]
    }

    registry = ProviderRegistry()
    registry.register(provider)

    return registry


def test_nested_provider_mutations_do_not_change_discovered_attributes():
    response = {
        "instance_id": "i-isolated-101",
        "state": {
            "name": "running",
            "details": {
                "reason": "initial",
            },
        },
        "tags": [
            {
                "key": "Environment",
                "value": "test",
            }
        ],
    }

    registry = make_registry(response)

    resource = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )[0]

    response["state"]["details"]["reason"] = "changed"
    response["tags"][0]["value"] = "production"
    response["tags"].append({"key": "Owner", "value": "changed"})

    assert resource.attributes["state"]["details"]["reason"] == "initial"
    assert resource.attributes["tags"] == [
        {
            "key": "Environment",
            "value": "test",
        }
    ]


def test_discovered_attribute_mutations_do_not_change_provider_response():
    response = {
        "instance_id": "i-isolated-102",
        "state": {
            "name": "running",
        },
        "tags": [
            {"key": "Environment", "value": "test"}
        ],
    }

    registry = make_registry(response)

    resource = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )[0]

    resource.attributes["state"]["name"] = "stopped"
    resource.attributes["tags"][0]["value"] = "production"
    resource.attributes["tags"].append(
        {"key": "Owner", "value": "new"}
    )

    assert response["state"]["name"] == "running"
    assert response["tags"] == [
        {"key": "Environment", "value": "test"}
    ]


def test_discovered_attributes_preserve_nested_values():
    response = {
        "instance_id": "i-isolated-103",
        "metadata": {
            "network": {
                "subnets": ["subnet-a", "subnet-b"],
            },
        },
    }

    registry = make_registry(response)

    resource = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )[0]

    assert resource.attributes == response
    assert resource.attributes is not response
    assert resource.attributes["metadata"] is not response["metadata"]
    assert (
        resource.attributes["metadata"]["network"]
        is not response["metadata"]["network"]
    )
    assert (
        resource.attributes["metadata"]["network"]["subnets"]
        is not response["metadata"]["network"]["subnets"]
    )