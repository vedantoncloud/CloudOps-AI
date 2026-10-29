from pathlib import Path
from unittest.mock import patch

import pytest
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
        return {"service": "cloudwatch", "status": "healthy", "instance_id": instance_id, "alarms": [], "next_token": None}

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
    assert 'id="loadFleetAlarms"' in html
    assert "api('/cloud/aws/ec2/alarms'+query)" in html


def test_fleet_cpu_alarms_follow_pages_and_drop_unrelated_alarms():
    payload = {"MetricAlarms": [{
        "AlarmName": "fleet-cpu", "StateValue": "ALARM", "AlarmArn": "private",
        "MetricName": "CPUUtilization", "Namespace": "AWS/EC2",
        "Dimensions": [{"Name": "InstanceId", "Value": "i-12345678"}],
    }], "NextToken": "next"}
    with patch("services.aws_service.boto3.client") as create_client:
        cw = create_client.return_value
        cw.describe_alarms.side_effect = [payload, {"MetricAlarms": [{
            "AlarmName": "other", "MetricName": "NetworkIn", "Namespace": "AWS/EC2",
            "Dimensions": [{"Name": "InstanceId", "Value": "i-12345678"}],
        }]}]
        result = AWSService().get_ec2_fleet_alarms("eu-west-3")
    assert result["status"] == "healthy"
    assert len(result["alarms"]) == 1
    assert result["alarms"][0]["AlarmName"] == "fleet-cpu"
    assert result["alarms"][0]["instance_ids"] == ["i-12345678"]
    assert "AlarmArn" not in result["alarms"][0]
    assert cw.describe_alarms.call_count == 2
    assert cw.describe_alarms.call_args_list[1].kwargs["NextToken"] == "next"


@pytest.mark.parametrize("bad_token", ["", 42, [], {}])
def test_instance_alarms_reject_malformed_next_tokens(bad_token):
    with patch("services.aws_service.boto3.client") as create_client:
        create_client.return_value.describe_alarms.return_value = {
            "MetricAlarms": [],
            "NextToken": bad_token,
        }
        result = AWSService().get_ec2_alarms("i-12345678")

    assert result["status"] == "unhealthy"
    assert result["error"] == "Malformed CloudWatch pagination token"


@pytest.mark.parametrize("bad_token", ["", 42, [], {}])
def test_fleet_alarms_reject_malformed_next_tokens(bad_token):
    with patch("services.aws_service.boto3.client") as create_client:
        create_client.return_value.describe_alarms.return_value = {
            "MetricAlarms": [],
            "NextToken": bad_token,
        }
        result = AWSService().get_ec2_fleet_alarms()

    assert result["status"] == "unhealthy"


def test_fleet_alarms_repeated_token_and_provider_failure_are_unhealthy():
    with patch("services.aws_service.boto3.client") as create_client:
        cw = create_client.return_value
        cw.describe_alarms.side_effect = [
            {"MetricAlarms": [], "NextToken": "repeat"},
            {"MetricAlarms": [], "NextToken": "repeat"},
        ]
        assert AWSService().get_ec2_fleet_alarms()["status"] == "unhealthy"
        cw.describe_alarms.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "secret"}}, "DescribeAlarms"
        )
        assert AWSService().get_ec2_fleet_alarms()["status"] == "unhealthy"


def test_fleet_alarm_endpoint_limits_tenant_to_owned_instances(monkeypatch):
    import main
    scoped_app = FastAPI()
    scoped_app.router.routes.extend(main.app.router.routes)
    scoped_app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "token-a": Principal("alice", "reader", "tenant-a"),
    })
    scoped = TestClient(scoped_app)
    monkeypatch.setattr(main.aws_service, "get_ec2_fleet_alarms", lambda **kwargs: {
        "service": "cloudwatch", "status": "healthy", "alarms": [
            {"AlarmName": "owned", "instance_ids": ["i-aaaaaaaa"]},
            {"AlarmName": "foreign", "instance_ids": ["i-bbbbbbbb"]},
        ],
    })
    monkeypatch.setattr(main, "_all_tenant_ec2_instances", lambda *_args: {
        "instances": [{"instance_id": "i-aaaaaaaa"}],
    })
    response = scoped.get("/cloud/aws/ec2/alarms?region=eu-west-3", headers={
        "Authorization": "Bearer token-a",
    })
    assert response.status_code == 200
    assert response.json()["alarms"] == [{"AlarmName": "owned", "instance_ids": ["i-aaaaaaaa"]}]


@pytest.mark.parametrize(
    "path,method_name,payload",
    [
        ("/cloud/aws/ec2/instances/i-12345678/alarms", "get_ec2_alarms", {
            "service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678",
            "alarms": {}, "next_token": None,
        }),
        ("/cloud/aws/ec2/instances/i-12345678/alarms", "get_ec2_alarms", {
            "service": "cloudwatch", "status": "healthy", "instance_id": "i-87654321",
            "alarms": [], "next_token": None,
        }),
        ("/cloud/aws/ec2/instances/i-12345678/alarms", "get_ec2_alarms", {
            "service": "cloudwatch", "status": "healthy", "instance_id": "i-12345678",
            "alarms": [{"AlarmName": "bad", "Threshold": float("nan")}], "next_token": None,
        }),
        ("/cloud/aws/ec2/alarms", "get_ec2_fleet_alarms", {
            "service": "cloudwatch", "status": "healthy",
            "alarms": [{"AlarmName": "bad", "instance_ids": ["not-an-instance"]}],
        }),
    ],
)
def test_ec2_alarm_routes_reject_malformed_healthy_payloads(monkeypatch, path, method_name, payload):
    import main

    monkeypatch.setattr(main.aws_service, method_name, lambda *args, **kwargs: payload)
    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}

def test_console_renders_filterable_fleet_alarm_summary_and_table():
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")
    assert 'id="alarmStateFilter"' in html
    assert 'value="INSUFFICIENT_DATA"' in html
    assert "function renderFleetAlarms(data" in html
    assert "counts.ALARM||0" in html
    assert "alarm.instance_ids.join(', ')" in html
    assert "$('alarmStateFilter').addEventListener('change'" in html
    assert "cell.textContent=value" in html


def test_fleet_alarm_csv_export_respects_filter_and_is_spreadsheet_safe():
    import json
    import re
    import shutil
    import subprocess

    import pytest

    if not shutil.which("node"):
        pytest.skip("Node.js is needed to run the console JavaScript behavior check")
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")
    assert 'id="exportFleetAlarms"' in html
    match = re.search(r"function exportFleetAlarms\(\).*?(?=function renderFleetAlarms)", html, re.S)
    assert match
    script = r"""
const assert=require('node:assert/strict'),source=JSON.parse(process.argv[1]);
let downloads=[],blobs=[];const filter={value:'ALARM'};
const csvCell=value=>{let text=String(value??'');if(/^[\t\r ]*[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'};
const document={body:{append(link){downloads.push(link)}},createElement(){return {click(){},remove(){}}}};
const URL={createObjectURL(blob){blobs.push(blob);return 'blob:test'},revokeObjectURL(){}};
const make=new Function('fleetAlarmData','filter','csvCell','URL','Blob','document',"const $=()=>filter;"+source+";return exportFleetAlarms");
(async()=>{
 const exportCsv=make({alarms:[{AlarmName:'=cmd',StateValue:'ALARM',instance_ids:['i-1'],Threshold:80,ComparisonOperator:'GreaterThanThreshold',Period:60,EvaluationPeriods:2},{AlarmName:'healthy',StateValue:'OK'}]},filter,csvCell,URL,Blob,document);
 exportCsv();assert.equal(downloads.length,1);assert.equal(downloads[0].download,'ec2-fleet-alarms.csv');const csv=await blobs[0].text();assert(csv.includes("'=cmd"));assert(csv.includes('GreaterThanThreshold 80'));assert(!csv.includes('healthy'));
 filter.value='INSUFFICIENT_DATA';exportCsv();assert.equal(downloads.length,1);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(["node", "-e", script, json.dumps(match.group(0))], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
