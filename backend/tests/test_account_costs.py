from unittest.mock import patch
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError
from auth import AccessControlMiddleware, Principal
from main import aws_account_costs
from services.aws_service import AWSService


def test_account_costs_requests_daily_unblended_totals():
    with patch("services.aws_service.boto3.client") as factory:
        client = factory.return_value
        client.get_cost_and_usage.return_value = {"ResultsByTime": [
            {"TimePeriod": {"Start": "2026-10-01"}, "Total": {"UnblendedCost": {"Amount": "1.25", "Unit": "USD"}}, "Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "1.00", "Unit": "USD"}}},
                {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.25", "Unit": "USD"}}},
            ]},
            {"TimePeriod": {"Start": "2026-10-02"}, "Total": {"UnblendedCost": {"Amount": "2.50", "Unit": "USD"}}, "Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "2.00", "Unit": "USD"}}},
                {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.50", "Unit": "USD"}}},
            ]},
        ]}
        result = AWSService().get_account_costs()
    factory.assert_called_once()
    assert factory.call_args.args == ("ce",)
    assert factory.call_args.kwargs["region_name"] == "us-east-1"
    assert factory.call_args.kwargs["config"].connect_timeout == 3
    args = client.get_cost_and_usage.call_args.kwargs
    assert args["Granularity"] == "DAILY" and args["Metrics"] == ["UnblendedCost"]
    assert args["GroupBy"] == [{"Type": "DIMENSION", "Key": "SERVICE"}]
    assert args["TimePeriod"]["End"] == datetime.now(timezone.utc).date().isoformat()
    assert result["currency"] == "USD" and result["total"] == 3.75
    assert result["daily"] == [{"date": "2026-10-01", "amount": 1.25}, {"date": "2026-10-02", "amount": 2.5}]
    assert result["services"] == [
        {"service": "Amazon EC2", "amount": 3.0},
        {"service": "Amazon S3", "amount": 0.75},
    ]


def test_account_costs_requests_selected_complete_day_window():
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.get_cost_and_usage.return_value = {"ResultsByTime": []}
        AWSService().get_account_costs(days=90)
    period = factory.return_value.get_cost_and_usage.call_args.kwargs["TimePeriod"]
    assert (datetime.fromisoformat(period["End"]) - datetime.fromisoformat(period["Start"])).days == 90


def test_account_costs_follows_cost_explorer_pages_without_double_counting_daily_totals():
    first_page = {"ResultsByTime": [{
        "TimePeriod": {"Start": "2026-10-01"},
        "Total": {"UnblendedCost": {"Amount": "3.00", "Unit": "USD"}},
        "Groups": [{"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "2.00", "Unit": "USD"}}}],
    }], "NextPageToken": "page-2"}
    second_page = {"ResultsByTime": [{
        "TimePeriod": {"Start": "2026-10-01"},
        "Total": {"UnblendedCost": {"Amount": "3.00", "Unit": "USD"}},
        "Groups": [{"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "1.00", "Unit": "USD"}}}],
    }]}
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.get_cost_and_usage.side_effect = [first_page, second_page]
        result = AWSService().get_account_costs()

    calls = factory.return_value.get_cost_and_usage.call_args_list
    assert len(calls) == 2
    assert "NextPageToken" not in calls[0].kwargs
    assert calls[1].kwargs["NextPageToken"] == "page-2"
    assert result["total"] == 3.0
    assert result["daily"] == [{"date": "2026-10-01", "amount": 3.0}]
    assert result["services"] == [
        {"service": "Amazon EC2", "amount": 2.0},
        {"service": "Amazon S3", "amount": 1.0},
    ]


def test_account_costs_does_not_return_partial_data_when_later_page_fails():
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.get_cost_and_usage.side_effect = [
            {"ResultsByTime": [], "NextPageToken": "page-2"},
            ClientError({"Error": {"Code": "ThrottlingException", "Message": "retry later"}}, "GetCostAndUsage"),
        ]
        result = AWSService().get_account_costs()
    assert result["status"] == "unhealthy"
    assert result["service"] == "aws-cost-explorer"


def test_account_costs_stops_on_repeated_page_token():
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.get_cost_and_usage.return_value = {"ResultsByTime": [], "NextPageToken": "repeat"}
        result = AWSService().get_account_costs()
    assert result["status"] == "unhealthy"
    assert factory.return_value.get_cost_and_usage.call_count == 2


def test_account_costs_service_returns_unhealthy_on_aws_error():
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.get_cost_and_usage.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetCostAndUsage")
        result = AWSService().get_account_costs()
    assert result["status"] == "unhealthy" and "AccessDeniedException" in result["error"]


def test_account_costs_api_requires_admin_token():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "reader": Principal("reader-1", "reader", "tenant-a"),
        "admin": Principal("admin-1", "admin", "tenant-a"),
    })
    app.add_api_route("/cloud/aws/account-costs", aws_account_costs)
    with patch("main.aws_service.get_account_costs", return_value={"status": "healthy", "total": 4.2}):
        client = TestClient(app)
        assert client.get("/cloud/aws/account-costs", headers={"Authorization": "Bearer reader"}).status_code == 403
        response = client.get("/cloud/aws/account-costs", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 200 and response.json()["total"] == 4.2


def test_account_costs_api_validates_and_forwards_selected_window():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "admin": Principal("admin-1", "admin", "tenant-a"),
    })
    app.add_api_route("/cloud/aws/account-costs", aws_account_costs)
    with patch("main.aws_service.get_account_costs", return_value={"status": "healthy", "days": 7}) as get_costs:
        client = TestClient(app)
        assert client.get("/cloud/aws/account-costs?days=6", headers={"Authorization": "Bearer admin"}).status_code == 400
        response = client.get("/cloud/aws/account-costs?days=7", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 200 and response.json()["days"] == 7
    get_costs.assert_called_once_with(days=7)


def test_account_costs_api_sanitizes_billing_failure():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "admin": Principal("admin-1", "admin", "tenant-a"),
    })
    app.add_api_route("/cloud/aws/account-costs", aws_account_costs)
    with patch("main.aws_service.get_account_costs", return_value={"status": "unhealthy", "error": "secret AWS details"}):
        response = TestClient(app).get("/cloud/aws/account-costs?days=30", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 503
    assert response.json()["detail"] == "AWS billing data is unavailable"
    assert "secret AWS details" not in response.text


def test_account_costs_api_sanitizes_provider_exception():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "admin": Principal("admin-1", "admin", "tenant-a"),
    })
    app.add_api_route("/cloud/aws/account-costs", aws_account_costs)
    with patch("main.aws_service.get_account_costs", side_effect=RuntimeError("private billing endpoint detail")):
        response = TestClient(app).get("/cloud/aws/account-costs?days=30", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS billing data is unavailable"}
    assert "private billing endpoint detail" not in response.text


def test_account_costs_api_rejects_malformed_provider_response():
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "admin": Principal("admin-1", "admin", "tenant-a"),
    })
    app.add_api_route("/cloud/aws/account-costs", aws_account_costs)
    with patch("main.aws_service.get_account_costs", return_value={"total": 5.0}):
        response = TestClient(app).get("/cloud/aws/account-costs?days=30", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS billing data is unavailable"}


def test_console_exposes_admin_account_billing_option():
    from pathlib import Path
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")
    assert 'value="billing">Account billing (admin)' in html
    assert 'id="billingWindow"' in html
    assert 'value="7">Last 7 complete days' in html and 'value="90">Last 90 complete days' in html
    assert "account-costs?days=${encodeURIComponent($('billingWindow').value)}" in html
    assert 'id="billingDaily"' in html and 'id="billingServices"' in html
    assert 'id="exportBilling" disabled' in html
    assert "data.daily.map(x=>[x.date,Number(x.amount).toFixed(2),data.currency||''])" in html
    assert "data.services.map(x=>[x.service,Number(x.amount).toFixed(2),data.currency||''])" in html
    assert "if(category==='billing'){box.textContent='Billing data loaded.';renderBilling(data)}" in html
    assert "billingData.daily.map(x=>['daily',x.date,x.amount,currency])" in html
    assert "row=>row.map(csvCell).join(',')" in html
    assert "data.daily.some(x=>!x||!x.date||!Number.isFinite(Number(x.amount)))" in html
    assert "data.services.some(x=>!x||typeof x.service!=='string'||!Number.isFinite(Number(x.amount)))" in html
    assert "$('billingReport').classList.add('hidden');$('exportBilling').disabled=true;billingData=null" in html
