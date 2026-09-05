from unittest.mock import MagicMock, patch
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

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]


def test_get_s3_objects_with_prefix():
    mock_s3 = MagicMock()

    mock_s3.list_objects_v2.return_value = {
        "Contents": [
            {
                "Key": "logs/app.log",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "logs/error.log",
                "Size": 200,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch(
        "services.aws_service.boto3.client",
        return_value=mock_s3,
    ):
        service = AWSService()
        result = service.get_s3_objects(
            "cloudops-test",
            prefix="logs/",
        )

    assert result["status"] == "healthy"
    assert result["bucket"] == "cloudops-test"
    assert result["prefix"] == "logs/"
    assert len(result["objects"]) == 2

    mock_s3.list_objects_v2.assert_called_once_with(
        Bucket="cloudops-test",
        Prefix="logs/",
    )


def test_get_s3_objects_with_max_keys():
    mock_s3 = MagicMock()

    mock_s3.list_objects_v2.return_value = {
        "Contents": [
            {
                "Key": "file1.txt",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "file2.txt",
                "Size": 200,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
            {
                "Key": "file3.txt",
                "Size": 300,
                "LastModified": datetime(2026, 9, 1, 12, 10, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch(
        "services.aws_service.boto3.client",
        return_value=mock_s3,
    ):
        service = AWSService()
        result = service.get_s3_objects(
            "cloudops-test",
            max_keys=2,
        )

    assert result["status"] == "healthy"
    assert len(result["objects"]) == 2
    assert result["objects"][0]["key"] == "file1.txt"
    assert result["objects"][1]["key"] == "file2.txt"

    mock_s3.list_objects_v2.assert_called_once_with(
        Bucket="cloudops-test",
        MaxKeys=2,
    )


def test_get_s3_objects_with_prefix_and_max_keys():
    mock_s3 = MagicMock()

    mock_s3.list_objects_v2.return_value = {
        "Contents": [
            {
                "Key": "logs/app.log",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "logs/error.log",
                "Size": 200,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch(
        "services.aws_service.boto3.client",
        return_value=mock_s3,
    ):
        service = AWSService()
        result = service.get_s3_objects(
            "cloudops-test",
            prefix="logs/",
            max_keys=2,
        )

    assert result["status"] == "healthy"
    assert result["bucket"] == "cloudops-test"
    assert result["prefix"] == "logs/"
    assert len(result["objects"]) == 2

    mock_s3.list_objects_v2.assert_called_once_with(
        Bucket="cloudops-test",
        Prefix="logs/",
        MaxKeys=2,
    )


def test_s3_objects_api_with_prefix():
    fake_response = {
        "Contents": [
            {
                "Key": "logs/app.log",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "logs/error.log",
                "Size": 200,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/objects?prefix=logs/"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["service"] == "s3"
    assert data["status"] == "healthy"
    assert data["bucket"] == "cloudops-test"
    assert data["prefix"] == "logs/"
    assert len(data["objects"]) == 2


def test_s3_objects_api_with_max_keys():
    fake_response = {
        "Contents": [
            {
                "Key": "file1.txt",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "file2.txt",
                "Size": 200,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
            {
                "Key": "file3.txt",
                "Size": 300,
                "LastModified": datetime(2026, 9, 1, 12, 10, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/objects?max_keys=2"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["service"] == "s3"
    assert data["status"] == "healthy"
    assert data["bucket"] == "cloudops-test"
    assert len(data["objects"]) == 2


def test_s3_objects_api_rejects_invalid_max_keys():
    client = TestClient(app)

    response = client.get(
        "/cloud/aws/s3/buckets/cloudops-test/objects?max_keys=0"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "max_keys must be between 1 and 1000"


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


def test_get_ec2_instance_status():
    fake_response = {
        "InstanceStatuses": [
            {
                "InstanceId": "i-1234567890",
                "InstanceState": {
                    "Name": "running"
                },
                "InstanceStatus": {
                    "Status": "ok"
                },
                "SystemStatus": {
                    "Status": "ok"
                },
            }
        ]
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value
        mock_ec2.describe_instance_status.return_value = fake_response

        result = AWSService().get_ec2_instance_status(
            "i-1234567890"
        )

    mock_ec2.describe_instance_status.assert_called_once_with(
        InstanceIds=["i-1234567890"],
        IncludeAllInstances=True,
    )

    assert result == {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "instance_status": "ok",
        "system_status": "ok",
        "state": "running",
    }


def test_get_ec2_instance_status_when_no_status():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value

        mock_ec2.describe_instance_status.return_value = {
            "InstanceStatuses": []
        }

        result = AWSService().get_ec2_instance_status(
            "i-1234567890"
        )

    assert result == {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "instance_status": None,
        "system_status": None,
        "state": None,
    }


def test_get_ec2_instance_status_access_denied():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_ec2 = mock_client.return_value

        mock_ec2.describe_instance_status.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            },
            "DescribeInstanceStatus",
        )

        result = AWSService().get_ec2_instance_status(
            "i-1234567890"
        )

    assert result["service"] == "ec2"
    assert result["status"] == "unhealthy"
    assert result["instance_id"] == "i-1234567890"
    assert "AccessDenied" in result["error"]


def test_get_ec2_metrics():
    cpu_response = {
        "Datapoints": [
            {
                "Average": 24.5,
                "Timestamp": datetime(2026, 9, 1, 10, 0, 0),
            }
        ]
    }

    network_responses = [
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

    status_response = {
        "InstanceStatuses": [
            {
                "InstanceId": "i-1234567890",
                "InstanceState": {
                    "Name": "running"
                },
                "InstanceStatus": {
                    "Status": "ok"
                },
                "SystemStatus": {
                    "Status": "ok"
                },
            }
        ]
    }

    cpu_client = MagicMock()
    cpu_client.get_metric_statistics.return_value = cpu_response

    network_client = MagicMock()
    network_client.get_metric_statistics.side_effect = network_responses

    ec2_client = MagicMock()
    ec2_client.describe_instance_status.return_value = status_response

    with patch(
        "services.aws_service.boto3.client",
        side_effect=[
            cpu_client,
            network_client,
            ec2_client,
        ],
    ):
        result = AWSService().get_ec2_metrics(
            "i-1234567890"
        )

    assert result["service"] == "ec2"
    assert result["status"] == "healthy"
    assert result["instance_id"] == "i-1234567890"

    assert result["cpu"]["service"] == "cloudwatch"
    assert result["cpu"]["value"] == 24.5

    assert result["network"]["service"] == "cloudwatch"
    assert result["network"]["metrics"]["NetworkIn"] == 12345.0
    assert result["network"]["metrics"]["NetworkOut"] == 67890.0

    assert result["instance_status"]["service"] == "ec2"
    assert result["instance_status"]["instance_status"] == "ok"
    assert result["instance_status"]["system_status"] == "ok"
    assert result["instance_status"]["state"] == "running"


def test_get_ec2_metrics_when_one_metric_is_unhealthy():
    with patch.object(
        AWSService,
        "get_ec2_cpu_utilization",
        return_value={
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metric": "CPUUtilization",
            "value": 24.5,
            "timestamp": "2026-09-01T10:00:00",
        },
    ), patch.object(
        AWSService,
        "get_ec2_network_utilization",
        return_value={
            "service": "cloudwatch",
            "status": "unhealthy",
            "instance_id": "i-1234567890",
            "error": "AccessDenied",
        },
    ), patch.object(
        AWSService,
        "get_ec2_instance_status",
        return_value={
            "service": "ec2",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "instance_status": "ok",
            "system_status": "ok",
            "state": "running",
        },
    ):
        result = AWSService().get_ec2_metrics(
            "i-1234567890"
        )

    assert result["service"] == "ec2"
    assert result["status"] == "unhealthy"
    assert result["instance_id"] == "i-1234567890"
    assert result["network"]["status"] == "unhealthy"


def test_ec2_metrics_api_success():
    fake_result = {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "cpu": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metric": "CPUUtilization",
            "value": 24.5,
            "timestamp": "2026-09-01T10:00:00",
        },
        "network": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metrics": {
                "NetworkIn": 12345.0,
                "NetworkOut": 67890.0,
            },
        },
        "instance_status": {
            "service": "ec2",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "instance_status": "ok",
            "system_status": "ok",
            "state": "running",
        },
    }

    with patch(
        "main.aws_service.get_ec2_metrics",
        return_value=fake_result,
    ):
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/ec2/instances/i-1234567890/metrics"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["service"] == "ec2"
    assert data["status"] == "healthy"
    assert data["instance_id"] == "i-1234567890"
    assert data["cpu"]["value"] == 24.5
    assert data["network"]["metrics"]["NetworkIn"] == 12345.0
    assert data["network"]["metrics"]["NetworkOut"] == 67890.0
    assert data["instance_status"]["state"] == "running"


def test_ec2_metrics_api_access_denied():
    fake_result = {
        "service": "ec2",
        "status": "unhealthy",
        "instance_id": "i-1234567890",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_ec2_metrics",
        return_value=fake_result,
    ):
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/ec2/instances/i-1234567890/metrics"
        )

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]


def test_ec2_metrics_api_rejects_invalid_instance_id():
    client = TestClient(app)

    response = client.get(
        "/cloud/aws/ec2/instances/invalid-instance-id/metrics"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid EC2 instance ID"


def test_ec2_metrics_api_accepts_valid_instance_id():
    fake_result = {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "cpu": {},
        "network": {},
        "instance_status": {},
    }

    with patch(
        "main.aws_service.get_ec2_metrics",
        return_value=fake_result,
    ) as mock_get_metrics:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/ec2/instances/i-1234567890/metrics"
        )

    assert response.status_code == 200
    assert response.json()["instance_id"] == "i-1234567890"
    mock_get_metrics.assert_called_once_with("i-1234567890")



def test_get_s3_bucket_health_healthy():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "cloudops-test",
        "prefix": None,
        "top_n": 1,
        "total_objects": 3,
        "total_size_bytes": 6000,
        "average_object_size_bytes": 2000,
        "largest_object": {
            "key": "large.zip",
            "size": 4000,
            "last_modified": "2026-09-01T12:00:00",
        },
        "objects": [
            {
                "key": "large.zip",
                "size": 4000,
                "last_modified": "2026-09-01T12:00:00",
            }
        ],
    }

    with patch.object(
        AWSService,
        "get_s3_largest_objects",
        return_value=fake_result,
    ) as mock_get_largest:
        result = AWSService().get_s3_bucket_health("cloudops-test")

    assert result["service"] == "s3"
    assert result["status"] == "healthy"
    assert result["bucket"] == "cloudops-test"
    assert result["health"] == "healthy"
    assert result["risk_count"] == 0
    assert result["risks"] == []
    assert result["total_objects"] == 3
    assert result["total_size_bytes"] == 6000
    assert result["average_object_size_bytes"] == 2000
    assert result["largest_object"]["key"] == "large.zip"

    mock_get_largest.assert_called_once_with(
        "cloudops-test",
        prefix=None,
        max_keys=None,
        top_n=1,
    )


def test_get_s3_bucket_health_empty_bucket():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "empty-bucket",
        "prefix": "logs/",
        "top_n": 1,
        "total_objects": 0,
        "total_size_bytes": 0,
        "average_object_size_bytes": 0,
        "largest_object": None,
        "objects": [],
    }

    with patch.object(
        AWSService,
        "get_s3_largest_objects",
        return_value=fake_result,
    ):
        result = AWSService().get_s3_bucket_health(
            "empty-bucket",
            prefix="logs/",
            max_keys=100,
        )

    assert result["status"] == "healthy"
    assert result["health"] == "warning"
    assert result["risk_count"] == 1
    assert result["risks"][0]["type"] == "empty_bucket"
    assert result["risks"][0]["severity"] == "low"
    assert result["total_objects"] == 0
    assert result["largest_object"] is None


def test_get_s3_bucket_health_access_denied():
    fake_result = {
        "service": "s3",
        "status": "unhealthy",
        "bucket": "private-bucket",
        "error": "AccessDenied",
    }

    with patch.object(
        AWSService,
        "get_s3_largest_objects",
        return_value=fake_result,
    ) as mock_get_largest:
        result = AWSService().get_s3_bucket_health("private-bucket")

    assert result["service"] == "s3"
    assert result["status"] == "unhealthy"
    assert result["bucket"] == "private-bucket"
    assert "AccessDenied" in result["error"]

    mock_get_largest.assert_called_once_with(
        "private-bucket",
        prefix=None,
        max_keys=None,
        top_n=1,
    )


def test_get_s3_largest_objects():
    fake_response = {
        "Contents": [
            {
                "Key": "small.txt",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "large.zip",
                "Size": 5000,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
            {
                "Key": "medium.log",
                "Size": 1000,
                "LastModified": datetime(2026, 9, 1, 12, 10, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        result = AWSService().get_s3_largest_objects(
            "cloudops-test"
        )

    assert result["service"] == "s3"
    assert result["status"] == "healthy"
    assert result["bucket"] == "cloudops-test"
    assert result["prefix"] is None
    assert result["top_n"] == 5
    assert result["total_objects"] == 3
    assert result["total_size_bytes"] == 6100
    assert result["average_object_size_bytes"] == 6100 / 3
    assert result["largest_object"]["key"] == "large.zip"
    assert result["largest_object"]["size"] == 5000
    assert len(result["objects"]) == 3
    assert result["objects"][0]["key"] == "large.zip"
    assert result["objects"][0]["size"] == 5000
    assert result["objects"][1]["key"] == "medium.log"
    assert result["objects"][2]["key"] == "small.txt"


def test_get_s3_largest_objects_with_top_n():
    fake_response = {
        "Contents": [
            {
                "Key": "file1.txt",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "file2.txt",
                "Size": 500,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
            {
                "Key": "file3.txt",
                "Size": 300,
                "LastModified": datetime(2026, 9, 1, 12, 10, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        result = AWSService().get_s3_largest_objects(
            "cloudops-test",
            top_n=2,
        )

    assert result["status"] == "healthy"
    assert result["top_n"] == 2
    assert result["total_objects"] == 3
    assert result["total_size_bytes"] == 900
    assert result["average_object_size_bytes"] == 300
    assert result["largest_object"]["key"] == "file2.txt"
    assert result["largest_object"]["size"] == 500
    assert len(result["objects"]) == 2
    assert result["objects"][0]["key"] == "file2.txt"
    assert result["objects"][1]["key"] == "file3.txt"


def test_get_s3_largest_objects_with_prefix():
    fake_response = {
        "Contents": [
            {
                "Key": "logs/app.log",
                "Size": 200,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "logs/error.log",
                "Size": 800,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        result = AWSService().get_s3_largest_objects(
            "cloudops-test",
            prefix="logs/",
        )

    assert result["status"] == "healthy"
    assert result["prefix"] == "logs/"
    assert result["objects"][0]["key"] == "logs/error.log"
    assert result["objects"][0]["size"] == 800

    mock_s3.list_objects_v2.assert_called_once_with(
        Bucket="cloudops-test",
        Prefix="logs/",
    )


def test_get_s3_largest_objects_with_max_keys():
    fake_response = {
        "Contents": [
            {
                "Key": "file1.txt",
                "Size": 100,
                "LastModified": datetime(2026, 9, 1, 12, 0, 0),
            },
            {
                "Key": "file2.txt",
                "Size": 500,
                "LastModified": datetime(2026, 9, 1, 12, 5, 0),
            },
            {
                "Key": "file3.txt",
                "Size": 300,
                "LastModified": datetime(2026, 9, 1, 12, 10, 0),
            },
        ],
        "IsTruncated": False,
    }

    with patch("services.aws_service.boto3.client") as mock_client:
        mock_s3 = mock_client.return_value
        mock_s3.list_objects_v2.return_value = fake_response

        result = AWSService().get_s3_largest_objects(
            "cloudops-test",
            max_keys=2,
        )

    assert result["status"] == "healthy"
    assert len(result["objects"]) == 2
    assert result["objects"][0]["key"] == "file2.txt"
    assert result["objects"][1]["key"] == "file1.txt"

    mock_s3.list_objects_v2.assert_called_once_with(
        Bucket="cloudops-test",
        MaxKeys=2,
    )


def test_get_s3_largest_objects_access_denied():
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

        result = AWSService().get_s3_largest_objects(
            "private-bucket"
        )

    assert result["service"] == "s3"
    assert result["status"] == "unhealthy"
    assert result["bucket"] == "private-bucket"
    assert "AccessDenied" in result["error"]


def test_s3_largest_objects_api_success():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "cloudops-test",
        "prefix": "logs/",
        "top_n": 3,
        "total_objects": 1,
        "total_size_bytes": 5000,
        "average_object_size_bytes": 5000,
        "largest_object": {
            "key": "logs/large.zip",
            "size": 5000,
            "last_modified": "2026-09-01T12:00:00",
        },
        "objects": [
            {
                "key": "logs/large.zip",
                "size": 5000,
                "last_modified": "2026-09-01T12:00:00",
            },
        ],
    }

    with patch(
        "main.aws_service.get_s3_largest_objects",
        return_value=fake_result,
    ) as mock_get_largest:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/largest-objects"
            "?prefix=logs/&max_keys=10&top_n=3"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["service"] == "s3"
    assert data["status"] == "healthy"
    assert data["bucket"] == "cloudops-test"
    assert data["prefix"] == "logs/"
    assert data["top_n"] == 3
    assert data["total_objects"] == 1
    assert data["total_size_bytes"] == 5000
    assert data["average_object_size_bytes"] == 5000
    assert data["largest_object"]["key"] == "logs/large.zip"
    assert data["largest_object"]["size"] == 5000
    assert data["objects"][0]["key"] == "logs/large.zip"

    mock_get_largest.assert_called_once_with(
        "cloudops-test",
        prefix="logs/",
        max_keys=10,
        top_n=3,
    )


def test_s3_largest_objects_api_rejects_invalid_top_n():
    client = TestClient(app)

    response = client.get(
        "/cloud/aws/s3/buckets/cloudops-test/largest-objects?top_n=0"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "top_n must be between 1 and 100"
    )


def test_s3_largest_objects_api_access_denied():
    fake_result = {
        "service": "s3",
        "status": "unhealthy",
        "bucket": "private-bucket",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_s3_largest_objects",
        return_value=fake_result,
    ):
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/private-bucket/largest-objects"
        )

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]

def test_s3_bucket_health_api_success():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "cloudops-test",
        "prefix": "logs/",
        "health": "healthy",
        "risk_count": 0,
        "risks": [],
        "total_objects": 3,
        "total_size_bytes": 6000,
        "average_object_size_bytes": 2000,
        "largest_object": {
            "key": "logs/large.zip",
            "size": 4000,
            "last_modified": "2026-09-01T12:00:00",
        },
    }

    with patch(
        "main.aws_service.get_s3_bucket_health",
        return_value=fake_result,
    ) as mock_get_health:
        client = TestClient(app)
        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/health"
            "?prefix=logs/&max_keys=100"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "s3"
    assert data["status"] == "healthy"
    assert data["bucket"] == "cloudops-test"
    assert data["prefix"] == "logs/"
    assert data["health"] == "healthy"
    assert data["risk_count"] == 0
    assert data["total_objects"] == 3
    assert data["largest_object"]["key"] == "logs/large.zip"

    mock_get_health.assert_called_once_with(
        "cloudops-test",
        prefix="logs/",
        max_keys=100,
    )


def test_s3_bucket_health_api_access_denied():
    fake_result = {
        "service": "s3",
        "status": "unhealthy",
        "bucket": "private-bucket",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_s3_bucket_health",
        return_value=fake_result,
    ):
        client = TestClient(app)
        response = client.get(
            "/cloud/aws/s3/buckets/private-bucket/health"
        )

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]

def test_s3_bucket_insights_api_success():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "cloudops-test",
        "prefix": "logs/",
        "health": "healthy",
        "risk_count": 1,
        "risks": [
            {
                "type": "large_object",
                "severity": "medium",
                "message": "Large object detected.",
            }
        ],
        "total_objects": 10,
        "total_size_bytes": 500000000,
        "average_object_size_bytes": 50000000,
        "largest_object": {
            "key": "logs/large.zip",
            "size": 200000000,
            "last_modified": "2026-09-01T12:00:00",
        },
    }

    with patch(
        "main.aws_service.get_s3_bucket_insights",
        return_value=fake_result,
    ) as mock_get_insights:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/insights"
            "?prefix=logs/&max_keys=100"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["service"] == "s3"
    assert data["status"] == "healthy"
    assert data["bucket"] == "cloudops-test"
    assert data["prefix"] == "logs/"
    assert data["risk_count"] == 1
    assert data["total_objects"] == 10
    assert data["largest_object"]["key"] == "logs/large.zip"

    mock_get_insights.assert_called_once_with(
        "cloudops-test",
        prefix="logs/",
        max_keys=100,
    )


def test_s3_bucket_insights_api_access_denied():
    fake_result = {
        "service": "s3",
        "status": "unhealthy",
        "bucket": "private-bucket",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_s3_bucket_insights",
        return_value=fake_result,
    ):
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/private-bucket/insights"
        )

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]


def test_s3_bucket_insights_api_rejects_invalid_max_keys():
    with patch("main.aws_service.get_s3_bucket_insights") as mock_get_insights:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/insights?max_keys=1001"
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "max_keys must be between 1 and 1000"

    mock_get_insights.assert_not_called()



def test_get_s3_bucket_optimization():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "cloudops-test",
        "prefix": None,
        "recommendation_count": 2,
        "recommendations": [
            {
                "type": "very_large_object",
                "priority": "medium",
                "message": "Bucket contains an object larger than 5 GB.",
                "recommendation": "Review large objects and consider compression, multipart-aware workflows, or lifecycle transitions where appropriate.",
            },
            {
                "type": "large_storage_footprint",
                "priority": "medium",
                "message": "Bucket storage footprint exceeds 100 GB.",
                "recommendation": "Review lifecycle policies and transition infrequently accessed data to appropriate storage classes.",
            },
        ],
        "total_objects": 10,
        "total_size_bytes": 150 * 1024 ** 3,
        "average_object_size_bytes": 15 * 1024 ** 3,
        "largest_object": {
            "key": "backup.tar",
            "size": 6 * 1024 ** 3,
            "last_modified": "2026-09-01T12:00:00",
        },
    }

    with patch.object(
        AWSService,
        "get_s3_largest_objects",
        return_value={
            "service": "s3",
            "status": "healthy",
            "bucket": "cloudops-test",
            "prefix": None,
            "top_n": 1,
            "total_objects": 10,
            "total_size_bytes": 150 * 1024 ** 3,
            "average_object_size_bytes": 15 * 1024 ** 3,
            "largest_object": {
                "key": "backup.tar",
                "size": 6 * 1024 ** 3,
                "last_modified": "2026-09-01T12:00:00",
            },
            "objects": [],
        },
    ) as mock_get_largest:
        result = AWSService().get_s3_bucket_optimization("cloudops-test")

    assert result["service"] == "s3"
    assert result["status"] == "healthy"
    assert result["bucket"] == "cloudops-test"
    assert result["recommendation_count"] == 2
    assert result["recommendations"][0]["type"] == "very_large_object"
    assert result["recommendations"][0]["priority"] == "medium"
    assert result["recommendations"][1]["type"] == "large_storage_footprint"
    assert result["total_objects"] == 10
    assert result["total_size_bytes"] == 150 * 1024 ** 3
    assert result["largest_object"]["key"] == "backup.tar"

    mock_get_largest.assert_called_once_with(
        "cloudops-test",
        prefix=None,
        max_keys=None,
        top_n=1,
    )


def test_get_s3_bucket_optimization_empty_bucket():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "empty-bucket",
        "prefix": None,
        "top_n": 1,
        "total_objects": 0,
        "total_size_bytes": 0,
        "average_object_size_bytes": 0,
        "largest_object": None,
        "objects": [],
    }

    with patch.object(
        AWSService,
        "get_s3_largest_objects",
        return_value=fake_result,
    ):
        result = AWSService().get_s3_bucket_optimization("empty-bucket")

    assert result["status"] == "healthy"
    assert result["recommendation_count"] == 1
    assert result["recommendations"][0]["type"] == "empty_bucket"
    assert result["recommendations"][0]["priority"] == "low"


def test_get_s3_bucket_optimization_access_denied():
    fake_result = {
        "service": "s3",
        "status": "unhealthy",
        "bucket": "private-bucket",
        "error": "AccessDenied",
    }

    with patch.object(
        AWSService,
        "get_s3_largest_objects",
        return_value=fake_result,
    ) as mock_get_largest:
        result = AWSService().get_s3_bucket_optimization("private-bucket")

    assert result["service"] == "s3"
    assert result["status"] == "unhealthy"
    assert result["bucket"] == "private-bucket"
    assert "AccessDenied" in result["error"]

    mock_get_largest.assert_called_once_with(
        "private-bucket",
        prefix=None,
        max_keys=None,
        top_n=1,
    )


def test_s3_bucket_optimization_api_success():
    fake_result = {
        "service": "s3",
        "status": "healthy",
        "bucket": "cloudops-test",
        "prefix": "logs/",
        "recommendation_count": 1,
        "recommendations": [
            {
                "type": "small_object_optimization",
                "priority": "low",
                "message": "Bucket contains many relatively small objects.",
                "recommendation": "Consider consolidating small files where practical to reduce object-management overhead.",
            }
        ],
        "total_objects": 1000,
        "total_size_bytes": 100000000,
        "average_object_size_bytes": 100000,
        "largest_object": {
            "key": "logs/app.log",
            "size": 500000,
            "last_modified": "2026-09-01T12:00:00",
        },
    }

    with patch(
        "main.aws_service.get_s3_bucket_optimization",
        return_value=fake_result,
    ) as mock_get_optimization:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/optimization"
            "?prefix=logs/&max_keys=100"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["service"] == "s3"
    assert data["status"] == "healthy"
    assert data["bucket"] == "cloudops-test"
    assert data["prefix"] == "logs/"
    assert data["recommendation_count"] == 1
    assert data["recommendations"][0]["type"] == "small_object_optimization"
    assert data["total_objects"] == 1000

    mock_get_optimization.assert_called_once_with(
        "cloudops-test",
        prefix="logs/",
        max_keys=100,
    )


def test_s3_bucket_optimization_api_access_denied():
    fake_result = {
        "service": "s3",
        "status": "unhealthy",
        "bucket": "private-bucket",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_s3_bucket_optimization",
        return_value=fake_result,
    ):
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/private-bucket/optimization"
        )

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]


def test_s3_bucket_optimization_api_rejects_invalid_max_keys():
    with patch("main.aws_service.get_s3_bucket_optimization") as mock_get_optimization:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/s3/buckets/cloudops-test/optimization?max_keys=1001"
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "max_keys must be between 1 and 1000"

    mock_get_optimization.assert_not_called()


def test_get_ec2_insights():
    metrics = {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "cpu": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metric": "CPUUtilization",
            "value": 24.5,
        },
        "network": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metrics": {
                "NetworkIn": 12345.0,
                "NetworkOut": 67890.0,
            },
        },
        "instance_status": {
            "service": "ec2",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "instance_status": "ok",
            "system_status": "ok",
            "state": "running",
        },
    }

    with patch.object(
        AWSService,
        "get_ec2_metrics",
        return_value=metrics,
    ):
        result = AWSService().get_ec2_insights("i-1234567890")

    assert result["service"] == "ec2"
    assert result["status"] == "healthy"
    assert result["instance_id"] == "i-1234567890"
    assert result["health"] == "healthy"
    assert result["insight_count"] == 0
    assert result["insights"] == []


def test_get_ec2_insights_high_cpu():
    metrics = {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "cpu": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metric": "CPUUtilization",
            "value": 85.0,
        },
        "network": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metrics": {
                "NetworkIn": 12345.0,
                "NetworkOut": 67890.0,
            },
        },
        "instance_status": {
            "service": "ec2",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "instance_status": "ok",
            "system_status": "ok",
            "state": "running",
        },
    }

    with patch.object(
        AWSService,
        "get_ec2_metrics",
        return_value=metrics,
    ):
        result = AWSService().get_ec2_insights("i-1234567890")

    assert result["health"] == "warning"
    assert result["insight_count"] == 1
    assert result["insights"][0]["type"] == "high_cpu_utilization"
    assert result["insights"][0]["severity"] == "high"


def test_get_ec2_insights_instance_status_issue():
    metrics = {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "cpu": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metric": "CPUUtilization",
            "value": 25.0,
        },
        "network": {
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metrics": {
                "NetworkIn": 12345.0,
                "NetworkOut": 67890.0,
            },
        },
        "instance_status": {
            "service": "ec2",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "instance_status": "impaired",
            "system_status": "ok",
            "state": "running",
        },
    }

    with patch.object(
        AWSService,
        "get_ec2_metrics",
        return_value=metrics,
    ):
        result = AWSService().get_ec2_insights("i-1234567890")

    assert result["health"] == "warning"
    assert result["insight_count"] == 1
    assert result["insights"][0]["type"] == "instance_status_issue"
    assert result["insights"][0]["severity"] == "high"


def test_ec2_insights_api_success():
    fake_result = {
        "service": "ec2",
        "status": "healthy",
        "instance_id": "i-1234567890",
        "health": "warning",
        "insight_count": 1,
        "insights": [
            {
                "type": "high_cpu_utilization",
                "severity": "high",
                "message": "EC2 instance CPU utilization is 80% or higher.",
                "recommendation": "Investigate CPU-intensive workloads and consider scaling or workload optimization.",
            }
        ],
    }

    with patch(
        "main.aws_service.get_ec2_insights",
        return_value=fake_result,
    ) as mock_get_insights:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/ec2/instances/i-1234567890/insights"
        )

    assert response.status_code == 200
    assert response.json()["service"] == "ec2"
    assert response.json()["status"] == "healthy"
    assert response.json()["instance_id"] == "i-1234567890"
    assert response.json()["health"] == "warning"
    assert response.json()["insight_count"] == 1
    assert response.json()["insights"][0]["type"] == "high_cpu_utilization"

    mock_get_insights.assert_called_once_with("i-1234567890")


def test_ec2_insights_api_access_denied():
    fake_result = {
        "service": "ec2",
        "status": "unhealthy",
        "instance_id": "i-1234567890",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_ec2_insights",
        return_value=fake_result,
    ):
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/ec2/instances/i-1234567890/insights"
        )

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]


def test_ec2_insights_api_rejects_invalid_instance_id():
    with patch("main.aws_service.get_ec2_insights") as mock_get_insights:
        client = TestClient(app)

        response = client.get(
            "/cloud/aws/ec2/instances/not-an-instance/insights"
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid EC2 instance ID"
    mock_get_insights.assert_not_called()


def test_get_ec2_efficiency_insights():
    instances = [
        {
            "instance_id": "i-1234567890",
            "name": "web-server",
            "state": "running",
            "instance_type": "t3.micro",
        },
        {
            "instance_id": "i-0987654321",
            "name": "old-server",
            "state": "stopped",
            "instance_type": "t3.micro",
        },
    ]

    with patch.object(
        AWSService,
        "get_ec2_instances",
        return_value={"service": "ec2", "status": "healthy", "instances": instances},
    ), patch.object(
        AWSService,
        "get_ec2_cpu_utilization",
        return_value={
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metric": "CPUUtilization",
            "value": 5.0,
        },
    ):
        result = AWSService().get_ec2_efficiency_insights()

    assert result["status"] == "healthy"
    assert result["health"] == "warning"
    assert result["insight_count"] == 2
    assert result["insights"][0]["type"] == "low_cpu_utilization"
    assert result["insights"][1]["type"] == "stopped_instance"


def test_get_ec2_efficiency_insights_healthy():
    instances = [{
        "instance_id": "i-1234567890",
        "name": "web-server",
        "state": "running",
    }]

    with patch.object(
        AWSService,
        "get_ec2_instances",
        return_value={"service": "ec2", "status": "healthy", "instances": instances},
    ), patch.object(
        AWSService,
        "get_ec2_cpu_utilization",
        return_value={
            "service": "cloudwatch",
            "status": "healthy",
            "instance_id": "i-1234567890",
            "metric": "CPUUtilization",
            "value": 35.0,
        },
    ):
        result = AWSService().get_ec2_efficiency_insights()

    assert result["health"] == "healthy"
    assert result["insight_count"] == 0
    assert result["insights"] == []


def test_get_ec2_efficiency_insights_inventory_failure():
    with patch.object(
        AWSService,
        "get_ec2_instances",
        return_value={
            "service": "ec2",
            "status": "unhealthy",
            "error": "AccessDenied",
        },
    ):
        result = AWSService().get_ec2_efficiency_insights()

    assert result["status"] == "unhealthy"
    assert "AccessDenied" in result["error"]


def test_ec2_efficiency_insights_api_success():
    fake_result = {
        "service": "ec2",
        "status": "healthy",
        "health": "warning",
        "insight_count": 1,
        "insights": [{"type": "stopped_instance", "severity": "medium"}],
        "instance_count": 2,
    }

    with patch(
        "main.aws_service.get_ec2_efficiency_insights",
        return_value=fake_result,
    ) as mock_get_insights:
        client = TestClient(app)
        response = client.get("/cloud/aws/ec2/efficiency-insights")

    assert response.status_code == 200
    assert response.json()["service"] == "ec2"
    assert response.json()["insight_count"] == 1
    mock_get_insights.assert_called_once_with()


def test_ec2_efficiency_insights_api_access_denied():
    fake_result = {
        "service": "ec2",
        "status": "unhealthy",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_ec2_efficiency_insights",
        return_value=fake_result,
    ):
        client = TestClient(app)
        response = client.get("/cloud/aws/ec2/efficiency-insights")

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]


def test_get_ec2_cost_insights():
    efficiency = {
        "service": "ec2",
        "status": "healthy",
        "health": "warning",
        "insight_count": 2,
        "insights": [
            {
                "type": "low_cpu_utilization",
                "instance_id": "i-1234567890",
                "instance_name": "web-server",
            },
            {
                "type": "stopped_instance",
                "instance_id": "i-0987654321",
                "instance_name": "old-server",
            },
        ],
        "instance_count": 2,
    }

    with patch.object(
        AWSService,
        "get_ec2_efficiency_insights",
        return_value=efficiency,
    ):
        result = AWSService().get_ec2_cost_insights()

    assert result["status"] == "healthy"
    assert result["health"] == "warning"
    assert result["insight_count"] == 2
    assert result["insights"][0]["type"] == "underutilized_instance_cost_risk"
    assert result["insights"][1]["type"] == "stopped_instance_cost_risk"
    assert result["instance_count"] == 2
    assert "qualitative" in result["note"]


def test_get_ec2_cost_insights_healthy():
    with patch.object(
        AWSService,
        "get_ec2_efficiency_insights",
        return_value={
            "service": "ec2",
            "status": "healthy",
            "health": "healthy",
            "insight_count": 0,
            "insights": [],
            "instance_count": 1,
        },
    ):
        result = AWSService().get_ec2_cost_insights()

    assert result["health"] == "healthy"
    assert result["insight_count"] == 0
    assert result["insights"] == []


def test_get_ec2_cost_insights_inventory_failure():
    with patch.object(
        AWSService,
        "get_ec2_efficiency_insights",
        return_value={
            "service": "ec2",
            "status": "unhealthy",
            "error": "AccessDenied",
        },
    ):
        result = AWSService().get_ec2_cost_insights()

    assert result["status"] == "unhealthy"
    assert "AccessDenied" in result["error"]


def test_ec2_cost_insights_api_success():
    fake_result = {
        "service": "ec2",
        "status": "healthy",
        "health": "warning",
        "insight_count": 1,
        "insights": [{"type": "stopped_instance_cost_risk", "severity": "medium"}],
        "instance_count": 2,
    }

    with patch(
        "main.aws_service.get_ec2_cost_insights",
        return_value=fake_result,
    ) as mock_get_insights:
        client = TestClient(app)
        response = client.get("/cloud/aws/ec2/cost-insights")

    assert response.status_code == 200
    assert response.json()["service"] == "ec2"
    assert response.json()["health"] == "warning"
    assert response.json()["insight_count"] == 1
    mock_get_insights.assert_called_once_with()


def test_ec2_cost_insights_api_access_denied():
    fake_result = {
        "service": "ec2",
        "status": "unhealthy",
        "error": "AccessDenied",
    }

    with patch(
        "main.aws_service.get_ec2_cost_insights",
        return_value=fake_result,
    ):
        client = TestClient(app)
        response = client.get("/cloud/aws/ec2/cost-insights")

    assert response.status_code == 403
    assert "AccessDenied" in response.json()["detail"]
