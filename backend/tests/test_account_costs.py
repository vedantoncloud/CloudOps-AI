from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError
from auth import AccessControlMiddleware, Principal
from main import aws_account_costs
from services.aws_service import AWSService


def _healthy_cost_result(days=30):
    return {
        "service": "aws-cost-explorer", "status": "healthy", "days": days,
        "period": {"start": "2026-09-23", "end_exclusive": "2026-10-23"},
        "comparison_period": {"start": "2026-08-24", "end_exclusive": "2026-09-23"},
        "currency": "USD", "total": 4.2, "previous_total": 3.0,
        "change": 1.2, "change_percent": 40.0,
        "daily": [{"date": "2026-10-22", "amount": 4.2}],
        "services": [{"service": "Amazon EC2", "amount": 4.2}],
    }


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
    assert (datetime.fromisoformat(period["End"]) - datetime.fromisoformat(period["Start"])).days == 180


def test_account_costs_compares_equal_windows_and_calculates_change():
    end = datetime.now(timezone.utc).date()
    current_start = end - timedelta(days=30)
    prior_start = current_start - timedelta(days=1)
    response = {"ResultsByTime": [
        {"TimePeriod": {"Start": prior_start.isoformat()}, "Total": {"UnblendedCost": {"Amount": "2", "Unit": "USD"}}, "Groups": []},
        {"TimePeriod": {"Start": current_start.isoformat()}, "Total": {"UnblendedCost": {"Amount": "5", "Unit": "USD"}}, "Groups": []},
    ]}
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.get_cost_and_usage.return_value = response
        result = AWSService().get_account_costs(days=30)
    period = factory.return_value.get_cost_and_usage.call_args.kwargs["TimePeriod"]
    assert period == {"Start": (end - timedelta(days=60)).isoformat(), "End": end.isoformat()}
    assert result["total"] == 5 and result["previous_total"] == 2
    assert result["change"] == 3 and result["change_percent"] == 150


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
    assert result["days"] == 30
    assert result["previous_total"] == 0
    assert result["change"] == 3.0 and result["change_percent"] is None


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
    assert result["error"] == "Repeated Cost Explorer page cursor"
    assert factory.return_value.get_cost_and_usage.call_count == 2


@pytest.mark.parametrize("bad_cursor", ["", "   ", 42, [], {}])
def test_account_costs_rejects_malformed_page_cursors(bad_cursor):
    with patch("services.aws_service.boto3.client") as factory:
        factory.return_value.get_cost_and_usage.return_value = {
            "ResultsByTime": [], "NextPageToken": bad_cursor
        }
        result = AWSService().get_account_costs()
    assert result["status"] == "unhealthy"
    assert result["error"] == "Malformed Cost Explorer page cursor"
    assert factory.return_value.get_cost_and_usage.call_count == 1


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
    with patch("main.aws_service.get_account_costs", return_value=_healthy_cost_result()):
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
    with patch("main.aws_service.get_account_costs", return_value=_healthy_cost_result(7)) as get_costs:
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


@pytest.mark.parametrize("field,value", [
    ("total", float("nan")),
    ("daily", [{"date": "not-a-date", "amount": 1.0}]),
    ("services", [{"service": "Amazon EC2", "amount": "1.0"}]),
    ("period", {"start": "2026-10-23", "end_exclusive": "2026-09-23"}),
])
def test_account_costs_api_rejects_malformed_healthy_payloads(field, value):
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "admin": Principal("admin-1", "admin", "tenant-a"),
    })
    app.add_api_route("/cloud/aws/account-costs", aws_account_costs)
    result = _healthy_cost_result()
    result[field] = value
    with patch("main.aws_service.get_account_costs", return_value=result):
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
    assert "data.previous_total" in html and "data.change_percent" in html
    assert "billingData.previous_total" in html and "billingData.change_percent" in html
    assert 'id="exportBilling" disabled' in html
    assert "data.daily.map(x=>[x.date,Number(x.amount).toFixed(2),data.currency||''])" in html
    assert "data.services.map(x=>[x.service,Number(x.amount).toFixed(2),data.currency||''])" in html
    assert "if(category==='billing'){box.textContent='Billing data loaded.';renderBilling(data)}" in html
    assert "billingData.daily.map(x=>['daily',x.date,x.amount,currency])" in html
    assert "row=>row.map(csvCell).join(',')" in html
    assert "data.daily.some(x=>!x||!x.date||!Number.isFinite(Number(x.amount)))" in html
    assert "data.services.some(x=>!x||typeof x.service!=='string'||!Number.isFinite(Number(x.amount)))" in html
    assert "$('billingReport').classList.add('hidden');$('exportBilling').disabled=true;billingData=null" in html
