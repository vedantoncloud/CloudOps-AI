from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.aws_service import AWSService


def test_get_ec2_instances_filters_exact_name_tag_and_paginates():
    with patch("services.aws_service.boto3.client") as mock_client:
        ec2 = mock_client.return_value
        ec2.describe_instances.return_value = {"Reservations": [], "NextToken": "next"}

        response = AWSService().get_ec2_instances(
            state="running", max_results=100, next_token="cursor", name="api-server"
        )

    ec2.describe_instances.assert_called_once_with(
        Filters=[
            {"Name": "instance-state-name", "Values": ["running"]},
            {"Name": "tag:Name", "Values": ["api-server"]},
        ],
        MaxResults=100,
        NextToken="cursor",
    )
    assert response["next_token"] == "next"


def test_ec2_inventory_name_filter_is_forwarded_to_aws_service():
    with patch("main.aws_service.get_ec2_instances", return_value={"status": "healthy", "instances": []}) as get_instances:
        response = TestClient(app).get("/cloud/aws/ec2/instances?name=api-server&max_results=100&next_token=cursor")

    assert response.status_code == 200
    get_instances.assert_called_once_with(None, None, 100, "cursor", name="api-server")


def test_ec2_inventory_rejects_blank_or_oversized_name_filter():
    client = TestClient(app)
    assert client.get("/cloud/aws/ec2/instances?name=%20%20").status_code == 400
    assert client.get("/cloud/aws/ec2/instances?name=" + "a" * 129).status_code == 400
