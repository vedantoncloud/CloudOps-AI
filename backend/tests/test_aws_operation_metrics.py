import json
import logging
from types import SimpleNamespace

from botocore.exceptions import ClientError

from observability import OperationMetrics, aws_operation_metrics
from services import aws_service as aws_module
from services.aws_service import AWSService


def test_operation_metrics_counts_success_and_failure_without_payloads():
    metrics = OperationMetrics()
    metrics.observe("get_ec2_instances", False)
    metrics.observe("get_ec2_instances", True)
    assert metrics.failure_snapshot() == {
        "scope": "since_process_start",
        "total_failures": 1,
        "operations": [
            {"operation": "get_ec2_instances", "calls": 2, "failures": 1}
        ],
    }
    assert "secret" not in str(metrics.failure_snapshot())


def test_aws_service_failure_results_are_counted_and_logged_without_error_details(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="cloudops.aws")
    before = aws_operation_metrics.failure_snapshot()
    calls = before.get("operations", [])
    old = next((x for x in calls if x["operation"] == "get_service_health"), {"calls": 0, "failures": 0})

    def fail_client(*args, **kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "private diagnostic"}}, "DescribeInstances")

    monkeypatch.setattr(aws_module, "_aws_client", fail_client)
    result = AWSService().get_service_health("ec2")
    assert result["status"] == "unhealthy"
    after = aws_operation_metrics.failure_snapshot()
    now = next(x for x in after["operations"] if x["operation"] == "get_service_health")
    assert now["calls"] == old["calls"] + 1
    assert now["failures"] == old["failures"] + 1
    assert "private diagnostic" not in str(after)
    record = json.loads(
        next(item.message for item in caplog.records if item.name == "cloudops.aws")
    )
    assert record == {
        "event": "aws_operation_failed",
        "operation": "get_service_health",
        "failure_kind": "provider_response",
    }
    assert "private diagnostic" not in caplog.text


def test_aws_success_operation_is_recorded(monkeypatch):
    before = aws_operation_metrics.failure_snapshot()
    old = next((x for x in before.get("operations", []) if x["operation"] == "get_service_health"), {"calls": 0, "failures": 0})
    monkeypatch.setattr(aws_module, "_aws_client", lambda *args, **kwargs: SimpleNamespace(describe_instances=lambda: {}))
    result = AWSService().get_service_health("ec2")
    assert result["status"] == "healthy"
    after = aws_operation_metrics.failure_snapshot()
    now = next(x for x in after["operations"] if x["operation"] == "get_service_health")
    assert now["calls"] == old["calls"] + 1
    assert now["failures"] == old["failures"]



def test_unhandled_aws_exceptions_log_type_without_exception_message(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="cloudops.aws")

    def fail_client(*args, **kwargs):
        raise RuntimeError("sensitive AWS endpoint and credential detail")

    monkeypatch.setattr(aws_module, "_aws_client", fail_client)
    try:
        AWSService().get_ec2_regions()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected the provider exception to propagate")

    record = json.loads(
        next(item.message for item in caplog.records if item.name == "cloudops.aws")
    )
    assert record["event"] == "aws_operation_failed"
    assert record["operation"] == "get_ec2_regions"
    assert record["failure_kind"] == "exception"
    assert record["exception_type"] == "RuntimeError"
    assert "sensitive AWS endpoint and credential detail" not in caplog.text
