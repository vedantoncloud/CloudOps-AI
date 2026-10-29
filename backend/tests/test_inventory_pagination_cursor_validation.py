import pytest

from services.aws_service import AWSService


CASES = [
    ("ec2-instance", "get_ec2_instances", {"max_results": 5, "next_token": "cursor"}, "NextToken", {"Reservations": []}, "EC2 instance"),
    ("ec2-volume", "get_ec2_volumes", {"max_results": 5, "next_token": "cursor"}, "NextToken", {"Volumes": []}, "EC2 volume"),
    ("ec2-snapshot", "get_ec2_snapshots", {"max_results": 5, "next_token": "cursor"}, "NextToken", {"Snapshots": []}, "EC2 snapshot"),
    ("rds-instance", "get_rds_instances", {"max_records": 20, "marker": "cursor"}, "Marker", {"DBInstances": []}, "RDS instance"),
    ("rds-snapshot", "get_rds_snapshots", {"max_records": 20, "marker": "cursor"}, "Marker", {"DBSnapshots": []}, "RDS snapshot"),
]


@pytest.mark.parametrize(
    "_case,method_name,method_args,cursor_key,response,resource",
    CASES,
)
def test_inventory_rejects_repeated_page_cursor(
    monkeypatch, _case, method_name, method_args, cursor_key, response, resource
):
    class Client:
        def __getattr__(self, name):
            if name.startswith("describe_"):
                return lambda **kwargs: {**response, cursor_key: "cursor"}
            raise AttributeError(name)

    monkeypatch.setattr("services.aws_service._aws_client", lambda *args, **kwargs: Client())
    result = getattr(AWSService(), method_name)(**method_args)

    assert result["status"] == "unhealthy"
    assert result["error"] == f"Repeated {resource} page cursor"


@pytest.mark.parametrize(
    "_case,method_name,method_args,cursor_key,response,resource",
    CASES,
)
@pytest.mark.parametrize("bad_cursor", ["", "   ", 42, [], {}])
def test_inventory_rejects_malformed_page_cursor(
    monkeypatch, _case, method_name, method_args, cursor_key, response, resource, bad_cursor
):
    class Client:
        def __getattr__(self, name):
            if name.startswith("describe_"):
                return lambda **kwargs: {**response, cursor_key: bad_cursor}
            raise AttributeError(name)

    monkeypatch.setattr("services.aws_service._aws_client", lambda *args, **kwargs: Client())
    result = getattr(AWSService(), method_name)(**method_args)

    assert result["status"] == "unhealthy"
    assert result["error"] == f"Malformed {resource} page cursor"
