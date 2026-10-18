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


def test_aws_service_failure_results_are_counted_without_error_details(monkeypatch):
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
