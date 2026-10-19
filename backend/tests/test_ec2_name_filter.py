from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from botocore.exceptions import ClientError
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


def test_ec2_inventory_forwards_selected_region_and_rejects_malformed_region():
    with patch("main.aws_service.get_ec2_instances", return_value={"status": "healthy", "instances": []}) as get_instances:
        response = TestClient(app).get("/cloud/aws/ec2/instances?region=ap-south-1&max_results=100")

    assert response.status_code == 200
    get_instances.assert_called_once_with(None, None, 100, None, name=None, region="ap-south-1")
    assert TestClient(app).get("/cloud/aws/ec2/instances?region=invalid-region").status_code == 400


def test_ec2_service_creates_regional_client_for_inventory():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_client.return_value.describe_instances.return_value = {"Reservations": []}

        result = AWSService().get_ec2_instances(region="ap-south-1")

    assert result["status"] == "healthy"
    assert mock_client.call_args.args == ("ec2",)
    assert mock_client.call_args.kwargs["region_name"] == "ap-south-1"


def test_ec2_inventory_filters_exact_instance_type_before_pagination():
    with patch("services.aws_service.boto3.client") as mock_client:
        ec2 = mock_client.return_value
        ec2.describe_instances.return_value = {"Reservations": [], "NextToken": "next"}
        response = AWSService().get_ec2_instances(
            instance_type="m7i.large", max_results=100, next_token="cursor"
        )

    assert response["is_truncated"] is True
    assert ec2.describe_instances.call_args.kwargs == {
        "Filters": [{"Name": "instance-type", "Values": ["m7i.large"]}],
        "MaxResults": 100,
        "NextToken": "cursor",
    }


def test_ec2_inventory_endpoint_forwards_instance_type_and_rejects_invalid_values():
    with patch("main.aws_service.get_ec2_instances", return_value={"status": "healthy", "instances": []}) as get_instances:
        response = TestClient(app).get("/cloud/aws/ec2/instances?instance_type=m7i.large&region=ap-south-1")

    assert response.status_code == 200
    get_instances.assert_called_once_with(None, None, instance_type="m7i.large", region="ap-south-1")
    client = TestClient(app)
    for value in ("", "   ", "m7i", "m7i.large, c7i.large", "a" * 65):
        assert client.get("/cloud/aws/ec2/instances", params={"instance_type": value}).status_code == 400


def test_ec2_instance_type_filter_preserves_provider_failure_state():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_client.return_value.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "provider unavailable"}},
            "DescribeInstances",
        )

        result = AWSService().get_ec2_instances(instance_type="c7i.large")

    assert result["status"] == "unhealthy"
    assert "provider unavailable" in result["error"]


def test_ec2_regional_inventory_preserves_aws_failure_response():
    with patch("services.aws_service.boto3.client") as mock_client:
        mock_client.return_value.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "provider unavailable"}},
            "DescribeInstances",
        )

        result = AWSService().get_ec2_instances(region="eu-west-3")

    assert result["status"] == "unhealthy"
    assert "provider unavailable" in result["error"]
    assert mock_client.call_args.kwargs["region_name"] == "eu-west-3"


def test_ec2_inventory_filters_vpc_and_subnet_before_pagination_and_returns_placement():
    with patch("services.aws_service.boto3.client") as mock_client:
        ec2 = mock_client.return_value
        ec2.describe_instances.return_value = {
            "Reservations": [{"Instances": [{
                "InstanceId": "i-12345678",
                "VpcId": "vpc-12345678",
                "SubnetId": "subnet-12345678",
            }]}],
            "NextToken": "next",
        }

        response = AWSService().get_ec2_instances(
            vpc_id="vpc-12345678", subnet_id="subnet-12345678",
            max_results=100, next_token="cursor",
        )

    assert ec2.describe_instances.call_args.kwargs == {
        "Filters": [
            {"Name": "vpc-id", "Values": ["vpc-12345678"]},
            {"Name": "subnet-id", "Values": ["subnet-12345678"]},
        ],
        "MaxResults": 100,
        "NextToken": "cursor",
    }
    assert response["instances"][0]["vpc_id"] == "vpc-12345678"
    assert response["instances"][0]["subnet_id"] == "subnet-12345678"
    assert response["next_token"] == "next"


def test_ec2_inventory_endpoint_forwards_network_filters_and_validates_ids():
    with patch("main.aws_service.get_ec2_instances", return_value={"status": "healthy", "instances": []}) as get_instances:
        response = TestClient(app).get(
            "/cloud/aws/ec2/instances?vpc_id=vpc-12345678&subnet_id=subnet-12345678"
        )

    assert response.status_code == 200
    get_instances.assert_called_once_with(
        None, None, vpc_id="vpc-12345678", subnet_id="subnet-12345678"
    )
    client = TestClient(app)
    assert client.get("/cloud/aws/ec2/instances?vpc_id=vpc-invalid").status_code == 400
    assert client.get("/cloud/aws/ec2/instances?subnet_id=subnet-invalid").status_code == 400


def test_ec2_network_filtered_inventory_sanitizes_provider_failure():
    with patch("main.aws_service.get_ec2_instances", return_value={
        "status": "unhealthy", "error": "private AWS diagnostic",
    }):
        response = TestClient(app).get(
            "/cloud/aws/ec2/instances?vpc_id=vpc-12345678"
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "private AWS diagnostic" not in response.text
