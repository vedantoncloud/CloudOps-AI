from unittest.mock import Mock

import pytest

from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


def make_registry():
    provider = Mock()
    provider.provider_name = "aws"

    registry = ProviderRegistry()
    registry.register(provider)

    return registry, provider


def test_discovers_ec2_instances_from_aws_reservations():
    registry, provider = make_registry()

    response = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-aws-101",
                        "State": {"Name": "running"},
                    },
                    {
                        "InstanceId": "i-aws-102",
                        "State": {"Name": "stopped"},
                    },
                ]
            },
            {
                "Instances": [
                    {
                        "InstanceId": "i-aws-103",
                        "State": {"Name": "running"},
                    }
                ]
            },
        ]
    }

    provider.get_ec2_instances.return_value = response

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )

    assert [r.resource_id for r in resources] == [
        "i-aws-101",
        "i-aws-102",
        "i-aws-103",
    ]

    assert resources[0].attributes == response["Reservations"][0]["Instances"][0]
    assert all(r.provider == "aws" for r in resources)
    assert all(r.resource_type == "ec2" for r in resources)
    assert all(r.read_only is True for r in resources)


def test_discovers_s3_buckets_from_aws_native_response():
    registry, provider = make_registry()

    response = {
        "Buckets": [
            {
                "Name": "cloudops-native-one",
                "CreationDate": "2026-10-12",
            },
            {
                "Name": "cloudops-native-two",
                "CreationDate": "2026-10-12",
            },
        ]
    }

    provider.get_s3_buckets.return_value = response

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        "s3",
    )

    assert [r.resource_id for r in resources] == [
        "cloudops-native-one",
        "cloudops-native-two",
    ]

    assert resources[0].attributes == response["Buckets"][0]
    assert all(r.provider == "aws" for r in resources)
    assert all(r.resource_type == "s3" for r in resources)
    assert all(r.read_only is True for r in resources)


@pytest.mark.parametrize(
    "response",
    [
        {"Reservations": []},
        {"Reservations": [{"Instances": []}]},
        {"Reservations": [{"Instances": None}]},
        {"Reservations": [{"Instances": "invalid"}]},
        {"Reservations": [{"Instances": [None, "invalid"]}]},
        {"Reservations": [None, "invalid"]},
        {"Reservations": [{"Instances": [{"State": "running"}]}]},
    ],
)
def test_invalid_or_empty_ec2_reservations_are_handled_safely(response):
    registry, provider = make_registry()
    provider.get_ec2_instances.return_value = response

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )

    assert resources == []


@pytest.mark.parametrize(
    "response",
    [
        {"Buckets": []},
        {"Buckets": None},
        {"Buckets": "invalid"},
        {"Buckets": [None, "invalid", {}]},
    ],
)
def test_invalid_or_empty_s3_native_responses_are_handled_safely(response):
    registry, provider = make_registry()
    provider.get_s3_buckets.return_value = response

    resources = ResourceDiscovery(registry).list_resources(
        "aws",
        "s3",
    )

    assert resources == []


def test_ec2_reservation_response_preserves_original_attributes():
    registry, provider = make_registry()

    instance = {
        "InstanceId": "i-preserved-101",
        "State": {"Name": "running"},
        "InstanceType": "t3.medium",
        "Tags": [{"Key": "Environment", "Value": "test"}],
    }

    provider.get_ec2_instances.return_value = {
        "Reservations": [{"Instances": [instance]}]
    }

    resource = ResourceDiscovery(registry).list_resources(
        "aws",
        "ec2",
    )[0]

    assert resource.attributes == instance


def test_s3_native_response_preserves_bucket_attributes():
    registry, provider = make_registry()

    bucket = {
        "Name": "cloudops-preserved",
        "CreationDate": "2026-10-12",
    }

    provider.get_s3_buckets.return_value = {
        "Buckets": [bucket]
    }

    resource = ResourceDiscovery(registry).list_resources(
        "aws",
        "s3",
    )[0]

    assert resource.attributes == bucket