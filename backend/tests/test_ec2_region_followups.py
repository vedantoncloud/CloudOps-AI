from pathlib import Path
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


def test_ec2_summary_uses_selected_region_and_rejects_invalid_region_before_provider_access():
    with patch("main.aws_service.get_ec2_summary", return_value={
        "service": "ec2", "status": "healthy", "total_instances": 4,
        "running_instances": 3, "stopped_instances": 1,
    }) as summary:
        response = client.get("/cloud/aws/ec2/summary?region=eu-west-3")
    assert response.status_code == 200
    assert response.json()["region"] == "eu-west-3"
    summary.assert_called_once_with(region="eu-west-3")

    with patch("main.aws_service.get_ec2_summary") as summary:
        invalid = client.get("/cloud/aws/ec2/summary?region=not-a-region")
    assert invalid.status_code == 400
    summary.assert_not_called()


def test_ec2_instance_details_exposes_platform_launch_and_iam_profile_context():
    details = {
        "instance_id": "i-12345678",
        "platform": "Ubuntu Pro",
        "architecture": "arm64",
        "launch_time": "2025-04-03T12:30:00+00:00",
        "iam_instance_profile_arn": "arn:aws:iam::123456789012:instance-profile/app",
        "tags": {},
    }
    with patch("main.aws_service.get_ec2_instance", return_value={"status": "healthy", "instance": details}):
        response = client.get("/cloud/aws/ec2/instances/i-12345678")

    assert response.status_code == 200
    assert response.json()["instance"] == details


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


def test_ec2_summary_service_uses_selected_region():
    with patch("services.aws_service.boto3.client") as create_client:
        ec2 = create_client.return_value
        ec2.describe_instances.return_value = {"Reservations": []}
        result = AWSService().get_ec2_summary(region="eu-west-3")

    assert result["status"] == "healthy"
    create_client.assert_called_once()
    assert create_client.call_args.args == ("ec2",)
    assert create_client.call_args.kwargs["region_name"] == "eu-west-3"


def test_aggregate_insights_use_selected_region_for_inventory_and_analysis(monkeypatch):
    from main import aws_service

    inventory_calls = []
    insight_calls = []

    def instances(state=None, tag=None, max_results=None, next_token=None, name=None, region=None):
        inventory_calls.append((next_token, region))
        return {
            "status": "healthy",
            "instances": [{"instance_id": "i-12345678", "state": "running"}],
            "next_token": "page-2" if next_token is None else None,
        }

    def insights(instances, region=None):
        insight_calls.append((instances, region))
        return {"service": "ec2", "status": "healthy", "instance_count": len(instances), "insights": []}

    monkeypatch.setattr(aws_service, "get_ec2_instances", instances)
    monkeypatch.setattr(aws_service, "get_ec2_efficiency_insights", insights)

    response = client.get("/cloud/aws/ec2/efficiency-insights?region=eu-west-3")

    assert response.status_code == 200
    assert inventory_calls == [(None, "eu-west-3"), ("page-2", "eu-west-3")]
    assert insight_calls[0][1] == "eu-west-3"
    assert response.json()["instance_count"] == 2


def test_aggregate_insights_reject_invalid_region_before_aws_access(monkeypatch):
    from main import aws_service

    monkeypatch.setattr(aws_service, "get_ec2_instances", lambda **kwargs: (_ for _ in ()).throw(AssertionError("AWS must not be called")))
    response = client.get("/cloud/aws/ec2/security-insights?region=not-a-region")
    assert response.status_code == 400


def test_aggregate_insights_without_region_keeps_configured_default(monkeypatch):
    from main import aws_service

    monkeypatch.setattr(aws_service, "get_ec2_security_insights", lambda: {"status": "healthy", "instance_count": 0, "insights": []})
    response = client.get("/cloud/aws/ec2/security-insights")
    assert response.status_code == 200
    assert response.json()["instance_count"] == 0


def test_console_passes_selected_region_to_fleet_insights():
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")
    assert "const query=region?`?region=${encodeURIComponent(region)}`:''" in html
    assert "`/cloud/aws/ec2/${category}-insights${query}`" in html
