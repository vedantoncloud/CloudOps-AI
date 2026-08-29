from unittest.mock import patch
from datetime import datetime

from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

from services.aws_service import AWSService
from main import app


def test_get_status_when_aws_is_connected():
    fake_identity = {
        "Account": "123456789012",
        "Arn": "arn:aws:iam::123456789012:user/cloudops-ai",
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_sts = mock_client.return_value
        mock_sts.get_caller_identity.return_value = fake_identity

        result = AWSService().get_status()

    assert result["provider"] == "AWS"
    assert result["status"] == "connected"
    assert result["account_id"] == "123456789012"
    assert result["arn"] == fake_identity["Arn"]


def test_get_service_health_for_sts():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_sts = mock_client.return_value
        mock_sts.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/cloudops-ai",
        }

        result = AWSService().get_service_health("sts")

    assert result == {
        "service": "sts",
        "status": "healthy",
    }


def test_get_service_health_for_unsupported_service():
    result = AWSService().get_service_health("lambda")

    assert result["service"] == "lambda"
    assert result["status"] == "unsupported"


def test_get_service_health_for_ec2():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value
        mock_ec2.describe_instances.return_value = {}

        result = AWSService().get_service_health("ec2")

    assert result == {
        "service": "ec2",
        "status": "healthy",
    }


def test_get_ec2_summary():
    fake_response = {
        "Reservations": [
            {
                "Instances": [
                    {"State": {"Name": "running"}},
                    {"State": {"Name": "stopped"}},
                    {"State": {"Name": "running"}},
                ]
            }
        ]
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value
        mock_ec2.describe_instances.return_value = fake_response

        result = AWSService().get_ec2_summary()

    assert result == {
        "service": "ec2",
        "status": "healthy",
        "total_instances": 3,
        "running_instances": 2,
        "stopped_instances": 1,
    }


def test_get_ec2_instances():
    fake_response = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-1234567890",
                        "State": {"Name": "running"},
                        "InstanceType": "t3.micro",
                        "Placement": {
                            "AvailabilityZone": "us-east-1a"
                        },
                        "PrivateIpAddress": "10.0.0.10",
                        "Tags": [],
                    }
                ]
            }
        ]
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value
        mock_ec2.describe_instances.return_value = fake_response

        result = AWSService().get_ec2_instances()

    assert result["service"] == "ec2"
    assert result["status"] == "healthy"
    assert isinstance(result["instances"], list)
    assert result["instances"][0]["instance_id"] == "i-1234567890"


def test_get_ec2_instances_with_state_filter():
    fake_response = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-1234567890",
                        "State": {"Name": "running"},
                        "InstanceType": "t3.micro",
                        "Placement": {
                            "AvailabilityZone": "us-east-1a"
                        },
                        "PrivateIpAddress": "10.0.0.10",
                        "Tags": [],
                    }
                ]
            }
        ]
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value
        mock_ec2.describe_instances.return_value = fake_response

        result = AWSService().get_ec2_instances("running")

    mock_ec2.describe_instances.assert_called_once_with(
        Filters=[
            {
                "Name": "instance-state-name",
                "Values": ["running"],
            }
        ]
    )

    assert result["service"] == "ec2"
    assert result["status"] == "healthy"
    assert isinstance(result["instances"], list)

    for instance in result["instances"]:
        assert instance["state"] == "running"


def test_ec2_instances_rejects_invalid_state():
    client = TestClient(app)

    response = client.get(
        "/cloud/aws/ec2/instances?state=invalid"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid EC2 state: invalid"


def test_get_ec2_instances_with_tag_filter():
    fake_response = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-1234567890",
                        "State": {"Name": "running"},
                        "InstanceType": "t3.micro",
                        "Placement": {
                            "AvailabilityZone": "us-east-1a"
                        },
                        "PrivateIpAddress": "10.0.0.10",
                        "Tags": [
                            {
                                "Key": "Name",
                                "Value": "web-server",
                            },
                            {
                                "Key": "Environment",
                                "Value": "production",
                            },
                        ],
                    }
                ]
            }
        ]
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value
        mock_ec2.describe_instances.return_value = fake_response

        result = AWSService().get_ec2_instances(
            tag="Environment:production"
        )

    mock_ec2.describe_instances.assert_called_once_with(
        Filters=[
            {
                "Name": "tag:Environment",
                "Values": ["production"],
            }
        ]
    )

    assert result["service"] == "ec2"
    assert result["status"] == "healthy"
    assert result["instances"][0]["name"] == "web-server"
    assert result["instances"][0]["tags"]["Environment"] == "production"


def test_get_s3_buckets():
    fake_response = {
        "Buckets": [
            {
                "Name": "cloudops-test",
                "CreationDate": datetime(2026, 8, 30, 10, 0, 0),
            }
        ]
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_buckets.return_value = fake_response

        result = AWSService().get_s3_buckets()

    assert result["service"] == "s3"
    assert result["status"] == "healthy"
    assert len(result["buckets"]) == 1
    assert result["buckets"][0]["name"] == "cloudops-test"
    assert result["buckets"][0]["creation_date"] == "2026-08-30T10:00:00"


def test_get_s3_buckets_when_access_denied():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_buckets.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "ListBuckets",
        )

        result = AWSService().get_s3_buckets()

    assert result["service"] == "s3"
    assert result["status"] == "unhealthy"
    assert "AccessDenied" in result["error"]