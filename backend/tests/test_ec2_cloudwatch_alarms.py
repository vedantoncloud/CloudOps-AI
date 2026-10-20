from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from auth import AccessControlMiddleware, Principal
from botocore.exceptions import ClientError
from main import app
from services.aws_service import AWSService


client = TestClient(app)


def test_ec2_cpu_alarms_are_bounded_region_aware_and_sanitized():
    response_payload = {
        "MetricAlarms": [{
            "AlarmName": "high-cpu",
            "AlarmDescription": "CPU above threshold",
            "StateValue": "ALARM",
            "StateReason": "Threshold crossed",
            "MetricName": "CPUUtilization",
            "Namespace": "AWS/EC2",
            "Dimensions": [{"Name": "InstanceId", "Value": "i-12345678"}],
            "Threshold": 80.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Period": 300,
            "EvaluationPeriods": 2,
            "TreatMissingData": "notBreaching",
            "AlarmArn": "must-not-be-returned",
        }, {
            "AlarmName": "other-instance",
            "MetricName": "CPUUtilization",
            "Namespace": "AWS/EC2",
            "Dimensions": [{"Name": "InstanceId", "Value": "i-87654321"}],
        }],
        "NextToken": "page-two",
    }
    with patch("services.aws_service.boto3.client") as create_client:
        cloudwatch = create_client.return_value
        cloudwatch.describe_alarms.return_value = response_payload
        result = AWSService().get_ec2_alarms(
            "i-12345678", next_token="page-one", region="eu-west-3"
        )

    assert create_client.call_args.args == ("cloudwatch",)
    assert create_client.call_args.kwargs["region_name"] == "eu-west-3"
    cloudwatch.describe_alarms.assert_called_once_with(
        AlarmTypes=["MetricAlarm"],
        MaxRecords=100,
        NextToken="page-one",
    )
    assert result["status"] == "healthy"
    assert result["next_token"] == "page-two"
    assert len(result["alarms"]) == 1
    assert result["alarms"][0]["AlarmName"] == "high-cpu"
    assert result["alarms"][0]["StateValue"] == "ALARM"
    assert "AlarmArn" not in result["alarms"][0]


def test_ec2_alarm_provider_exception_returns_unhealthy_result():
    with patch("services.aws_service.boto3.client") as create_client:
        create_client.return_value.describe_alarms.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "sensitive details"}},
            "DescribeAlarmsForMetric",
        )
        result = AWSService().get_ec2_alarms("i-12345678")

    assert result["status"] == "unhealthy"
    assert result["instance_id"] == "i-12345678"
    assert "AccessDenied" in result["error"]


def test_ec2_alarm_provider_failure_becomes_sanitized_dependency_response(monkeypatch):
    from main import aws_service

    monkeypatch.setattr(aws_service, "get_ec2_alarms", lambda *_args, **_kwargs: {
        "status": "unhealthy", "error": "secret account diagnostics",
    })
    response = client.get("/cloud/aws/ec2/instances/i-12345678/alarms")
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "secret" not in response.text


def test_ec2_alarm_endpoint_rejects_invalid_instance_and_region_before_provider(monkeypatch):
    from main import aws_service

    monkeypatch.setattr(aws_service, "get_ec2_alarms", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called")))
    assert client.get("/cloud/aws/ec2/instances/bad/alarms").status_code == 400
    assert client.get("/cloud/aws/ec2/instances/i-12345678/alarms?region=bad").status_code == 400


def test_ec2_alarms_require_tenant_ownership_and_use_selected_region(monkeypatch):
    import main

    scoped_app = FastAPI()
    scoped_app.router.routes.extend(main.app.router.routes)
    scoped_app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"token-a": Principal("alice", "reader", "tenant-a")},
    )
    scoped_client = TestClient(scoped_app)
    service = main.aws_service
    monkeypatch.setattr(service, "get_ec2_instance", lambda instance_id, **kwargs: {
        "status": "healthy",
        "instance": {
            "instance_id": instance_id,
            "tags": {"CloudOpsTenantId": "tenant-a"},
        },
    })
    calls = []

    def get_alarms(instance_id, **kwargs):
        calls.append((instance_id, kwargs))
        return {"status": "healthy", "alarms": [], "next_token": None}

    monkeypatch.setattr(service, "get_ec2_alarms", get_alarms)
    response = scoped_client.get(
        "/cloud/aws/ec2/instances/i-aaaaaaaa/alarms?region=eu-west-3",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 200
    assert calls == [("i-aaaaaaaa", {"next_token": None, "region": "eu-west-3"})]

    monkeypatch.setattr(service, "get_ec2_instance", lambda *_args, **_kwargs: {
        "status": "healthy",
        "instance": {
            "instance_id": "i-bbbbbbbb",
            "tags": {"CloudOpsTenantId": "tenant-b"},
        },
    })
    hidden = scoped_client.get(
        "/cloud/aws/ec2/instances/i-bbbbbbbb/alarms",
        headers={"Authorization": "Bearer token-a"},
    )
    assert hidden.status_code == 404
    assert len(calls) == 1


def test_console_shows_ec2_alarm_details():
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")
    assert "['CloudWatch alarms',root+'/alarms'+regional]" in html
    assert "No CPU utilization alarms are configured for this instance." in html
    assert "More alarms" in html
    assert "loadMoreInstanceAlarms(root,regional" in html
