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


def test_s3_bucket_details():
    fake_response = {
        "LocationConstraint": "ap-south-1"
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.get_bucket_location.return_value = fake_response

        result = AWSService().get_s3_bucket_details("cloudops-test")

    mock_s3.get_bucket_location.assert_called_once_with(
        Bucket="cloudops-test"
    )

    assert result == {
        "service": "s3",
        "status": "healthy",
        "bucket": "cloudops-test",
        "region": "ap-south-1",
    }


def test_s3_bucket_details_access_denied():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.get_bucket_location.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "GetBucketLocation",
        )

        result = AWSService().get_s3_bucket_details("test-bucket")

    assert result["service"] == "s3"
    assert result["status"] == "unhealthy"
    assert result["bucket"] == "test-bucket"
    assert "AccessDenied" in result["error"]


def test_get_s3_objects():
    fake_response = {
        "Contents": [
            {
                "Key": "test/file.txt",
                "Size": 1024,
                "LastModified": datetime(2026, 8, 31, 10, 0, 0),
            },
            {
                "Key": "images/logo.png",
                "Size": 2048,
                "LastModified": datetime(2026, 8, 31, 11, 0, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        result = AWSService().get_s3_objects("cloudops-test")

    mock_s3.list_objects_v2.assert_called_once_with(
        Bucket="cloudops-test"
    )

    assert result["service"] == "s3"
    assert result["status"] == "healthy"
    assert result["bucket"] == "cloudops-test"
    assert len(result["objects"]) == 2
    assert result["objects"][0]["key"] == "test/file.txt"
    assert result["objects"][0]["size"] == 1024
    assert result["objects"][0]["last_modified"] == "2026-08-31T10:00:00"


def test_get_s3_objects_empty_bucket():
    fake_response = {
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        result = AWSService().get_s3_objects("empty-bucket")

    assert result["service"] == "s3"
    assert result["status"] == "healthy"
    assert result["bucket"] == "empty-bucket"
    assert result["objects"] == []


def test_get_s3_objects_pagination():
    first_response = {
        "Contents": [
            {
                "Key": "file1.txt",
                "Size": 100,
                "LastModified": datetime(2026, 8, 31, 10, 0, 0),
            }
        ],
        "IsTruncated": True,
        "NextContinuationToken": "token-123",
    }

    second_response = {
        "Contents": [
            {
                "Key": "file2.txt",
                "Size": 200,
                "LastModified": datetime(2026, 8, 31, 11, 0, 0),
            }
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.side_effect = [
            first_response,
            second_response,
        ]

        result = AWSService().get_s3_objects("cloudops-test")

    assert result["service"] == "s3"
    assert result["status"] == "healthy"
    assert result["bucket"] == "cloudops-test"
    assert len(result["objects"]) == 2

    assert result["objects"][0]["key"] == "file1.txt"
    assert result["objects"][1]["key"] == "file2.txt"

    assert mock_s3.list_objects_v2.call_count == 2

    mock_s3.list_objects_v2.assert_any_call(
        Bucket="cloudops-test"
    )

    mock_s3.list_objects_v2.assert_any_call(
        Bucket="cloudops-test",
        ContinuationToken="token-123",
    )


def test_get_s3_objects_access_denied():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "ListObjectsV2",
        )

        result = AWSService().get_s3_objects("private-bucket")

    assert result["service"] == "s3"
    assert result["status"] == "unhealthy"
    assert result["bucket"] == "private-bucket"
    assert "AccessDenied" in result["error"]


def test_s3_objects_api_success():
    fake_response = {
        "Contents": [
            {
                "Key": "test/file.txt",
                "Size": 1024,
                "LastModified": datetime(2026, 8, 31, 10, 0, 0),
            }
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/objects"
        )

    assert response.status_code == 200
    assert response.json()["service"] == "s3"
    assert response.json()["status"] == "healthy"
    assert response.json()["bucket"] == "cloudops-test"
    assert len(response.json()["objects"]) == 1
    assert response.json()["objects"][0]["key"] == "test/file.txt"


def test_s3_objects_api_access_denied():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "ListObjectsV2",
        )

        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/private-bucket/objects"
        )
def test_get_ec2_cpu_utilization():
    fake_response = {
        "Datapoints": [
            {
                "Average": 24.5,
                "Timestamp": datetime(2026, 9, 1, 10, 0, 0),
            }
        ]
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_cloudwatch = mock_client.return_value
        mock_cloudwatch.get_metric_statistics.return_value = fake_response

        result = AWSService().get_ec2_cpu_utilization(
            "i-1234567890"
        )

    assert result["service"] == "cloudwatch"
    assert result["status"] == "healthy"
    assert result["instance_id"] == "i-1234567890"
    assert result["metric"] == "CPUUtilization"
    assert result["value"] == 24.5
    assert result["timestamp"] == "2026-09-01T10:00:00"


def test_get_ec2_cpu_utilization_when_no_datapoints():
    fake_response = {
        "Datapoints": []
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_cloudwatch = mock_client.return_value
        mock_cloudwatch.get_metric_statistics.return_value = fake_response

        result = AWSService().get_ec2_cpu_utilization(
            "i-1234567890"
        )

    assert result["service"] == "cloudwatch"
    assert result["status"] == "healthy"
    assert result["instance_id"] == "i-1234567890"
    assert result["metric"] == "CPUUtilization"
    assert result["value"] is None


def test_get_ec2_cpu_utilization_access_denied():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_cloudwatch = mock_client.return_value
        mock_cloudwatch.get_metric_statistics.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "GetMetricStatistics",
        )

        result = AWSService().get_ec2_cpu_utilization(
            "i-1234567890"
        )

    assert result["service"] == "cloudwatch"
    assert result["status"] == "unhealthy"
    assert result["instance_id"] == "i-1234567890"
    assert "AccessDenied" in result["error"]

def test_get_ec2_network_utilization():
    fake_timestamp = datetime(2026, 9, 1, 10, 0, 0)

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_cloudwatch = mock_client.return_value

        mock_cloudwatch.get_metric_statistics.side_effect = [
            {
                "Datapoints": [
                    {
                        "Average": 12345.0,
                        "Timestamp": fake_timestamp,
                    }
                ]
            },
            {
                "Datapoints": [
                    {
                        "Average": 67890.0,
                        "Timestamp": fake_timestamp,
                    }
                ]
            },
        ]

        result = AWSService().get_ec2_network_utilization(
            "i-1234567890"
        )

    assert result["service"] == "cloudwatch"
    assert result["status"] == "healthy"
    assert result["instance_id"] == "i-1234567890"

    assert result["metrics"]["NetworkIn"] == 12345.0
    assert result["metrics"]["NetworkOut"] == 67890.0

    assert mock_cloudwatch.get_metric_statistics.call_count == 2


def test_get_ec2_network_utilization_when_no_datapoints():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_cloudwatch = mock_client.return_value

        mock_cloudwatch.get_metric_statistics.return_value = {
            "Datapoints": []
        }

        result = AWSService().get_ec2_network_utilization(
            "i-1234567890"
        )

    assert result["service"] == "cloudwatch"
    assert result["status"] == "healthy"
    assert result["instance_id"] == "i-1234567890"
    assert result["metrics"]["NetworkIn"] is None
    assert result["metrics"]["NetworkOut"] is None


def test_get_ec2_network_utilization_access_denied():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_cloudwatch = mock_client.return_value

        mock_cloudwatch.get_metric_statistics.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "GetMetricStatistics",
        )

        result = AWSService().get_ec2_network_utilization(
            "i-1234567890"
        )

    assert result["service"] == "cloudwatch"
    assert result["status"] == "unhealthy"
    assert result["instance_id"] == "i-1234567890"
    assert "AccessDenied" in result["error"]

def test_network_objects_api_success():
    client = TestClient(app)

    with patch(
        "services.aws_service.boto3.client"
    ) as mock_client:
        mock_cloudwatch = mock_client.return_value

        mock_cloudwatch.get_metric_statistics.side_effect = [
            {
                "Datapoints": [
                    {
                        "Average": 12345.0,
                        "Timestamp": datetime(2026, 9, 1, 10, 0, 0),
                    }
                ]
            },
            {
                "Datapoints": [
                    {
                        "Average": 67890.0,
                        "Timestamp": datetime(2026, 9, 1, 10, 0, 0),
                    }
                ]
            },
        ]

        response = client.get(
            "/cloud/aws/ec2/instances/i-1234567890/network"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["service"] == "cloudwatch"
    assert data["status"] == "healthy"
    assert data["instance_id"] == "i-1234567890"
    assert data["metrics"]["NetworkIn"] == 12345.0
    assert data["metrics"]["NetworkOut"] == 67890.0


def test_network_objects_api_access_denied():
    client = TestClient(app)

    with patch(
        "services.aws_service.boto3.client"
    ) as mock_client:
        mock_cloudwatch = mock_client.return_value

        mock_cloudwatch.get_metric_statistics.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "GetMetricStatistics",
        )

        response = client.get(
            "/cloud/aws/ec2/instances/i-1234567890/network"
        )

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]