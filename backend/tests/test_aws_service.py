from unittest.mock import patch

from services.aws_service import AWSService


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