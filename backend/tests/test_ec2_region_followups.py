from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.aws_service import AWSService


client = TestClient(app)


def test_ec2_instance_details_uses_selected_region_and_surfaces_unavailable_region():
    with patch("main.aws_service.get_ec2_instance", return_value={"status": "healthy", "instance": {"instance_id": "i-12345678", "tags": {}}}) as lookup:
        response = client.get("/cloud/aws/ec2/instances/i-12345678?region=eu-west-3")
    assert response.status_code == 200
    lookup.assert_called_once_with("i-12345678", region="eu-west-3")

    with patch("main.aws_service.get_ec2_instance", return_value={"status": "unhealthy"}):
        failed = client.get("/cloud/aws/ec2/instances/i-12345678?region=eu-west-3")
    assert failed.status_code == 503


def test_ec2_metrics_and_planning_keep_selected_region_and_reject_invalid_region():
    with patch("main.aws_service.get_ec2_metrics", return_value={"status": "healthy"}) as metrics:
        response = client.get("/cloud/aws/ec2/instances/i-12345678/metrics?region=ap-south-1&lookback_hours=6")
    assert response.status_code == 200
    metrics.assert_called_once_with("i-12345678", lookback_hours=6, region="ap-south-1")
    assert client.get("/cloud/aws/ec2/instances/i-12345678/metrics?region=not-a-region").status_code == 400

    with patch("autonomy.api.aws_service.get_ec2_insights", return_value={"status": "healthy", "insights": []}) as insights:
        planned = client.post("/autonomy/ec2/instances/i-12345678/plans?region=eu-west-3")
    assert planned.status_code == 200
    insights.assert_called_once_with("i-12345678", region="eu-west-3")
    assert client.post("/autonomy/ec2/instances/i-12345678/plans?region=bad").status_code == 400


def test_ec2_service_uses_region_for_instance_and_cloudwatch_calls():
    with patch("services.aws_service.boto3.client") as create_client:
        ec2, cloudwatch = create_client.side_effect = [type("EC2", (), {"describe_instances": lambda self, **kwargs: {"Reservations": [{"Instances": [{"InstanceId": "i-12345678", "State": {"Name": "running"}}]}]}})(), type("CW", (), {"get_metric_statistics": lambda self, **kwargs: {"Datapoints": []}})()]
        service = AWSService()
        instance = service.get_ec2_instance("i-12345678", region="eu-west-3")
        assert instance["status"] == "healthy"
        service.get_ec2_cpu_utilization("i-12345678", region="eu-west-3")

    assert create_client.call_args_list[0].kwargs["region_name"] == "eu-west-3"
    assert create_client.call_args_list[1].kwargs["region_name"] == "eu-west-3"
