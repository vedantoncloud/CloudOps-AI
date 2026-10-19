from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from main import app
from services.aws_service import AWSService


client = TestClient(app)


def test_get_ec2_regions_returns_sorted_unique_enabled_region_names():
    with patch("services.aws_service.boto3.client") as create_client:
        create_client.return_value.describe_regions.return_value = {
            "Regions": [
                {"RegionName": "us-west-2", "OptInStatus": "opted-in"},
                {"RegionName": "ap-south-1", "OptInStatus": "opt-in-not-required"},
                {"RegionName": "us-west-2", "OptInStatus": "opted-in"},
                {"RegionName": "   "},
                {"OptInStatus": "opted-in"},
            ]
        }

        result = AWSService().get_ec2_regions()

    assert create_client.call_args.args == ("ec2",)
    assert create_client.call_args.kwargs["config"].read_timeout == 30
    create_client.return_value.describe_regions.assert_called_once_with(AllRegions=False)
    assert result == {
        "service": "ec2",
        "status": "healthy",
        "regions": ["ap-south-1", "us-west-2"],
    }


def test_regions_api_returns_enabled_regions():
    with patch("main.aws_service.get_ec2_regions", return_value={
        "service": "ec2", "status": "healthy", "regions": ["eu-west-1"]
    }) as get_regions:
        response = client.get("/cloud/aws/ec2/regions")

    assert response.status_code == 200
    assert response.json() == {
        "service": "ec2", "status": "healthy", "regions": ["eu-west-1"]
    }
    get_regions.assert_called_once_with()


def test_regions_api_hides_provider_error_details():
    with patch("main.aws_service.get_ec2_regions", return_value={
        "service": "ec2", "status": "unhealthy", "error": "sensitive account detail"
    }):
        response = client.get("/cloud/aws/ec2/regions")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "sensitive" not in response.text


def test_region_discovery_failure_is_stable_and_does_not_expose_sdk_details():
    with patch("services.aws_service.boto3.client") as create_client:
        create_client.return_value.describe_regions.side_effect = ClientError(
            {"Error": {"Code": "UnauthorizedOperation", "Message": "private detail"}},
            "DescribeRegions",
        )

        result = AWSService().get_ec2_regions()

    assert result == {"service": "ec2", "status": "unhealthy"}


def test_console_offers_region_suggestions_and_keeps_manual_fallback():
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")

    assert 'list="ec2Regions"' in html
    assert 'id="refreshRegions"' in html
    assert "api('/cloud/aws/ec2/regions')" in html
    assert "You can still enter a region manually." in html
