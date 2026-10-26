from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from autonomy import api as autonomy_api


client = TestClient(app)


def _tenant_request(tenant_id="tenant-a"):
    return SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id=tenant_id))


def test_tenant_ec2_plan_ownership_accepts_matching_well_formed_resource():
    with patch("autonomy.api.aws_service.get_ec2_instance", return_value={
        "status": "healthy",
        "instance": {"instance_id": "i-123456789", "tags": {"CloudOpsTenantId": "tenant-a"}},
    }) as lookup:
        autonomy_api._require_tenant_ec2_instance(_tenant_request(), "i-123456789")

    lookup.assert_called_once_with("i-123456789")


@pytest.mark.parametrize("instance", [
    "malformed",
    {},
    {"instance_id": "i-987654321", "tags": {}},
    {"instance_id": "i-123456789", "tags": []},
    {"instance_id": "i-123456789", "tags": {"CloudOpsTenantId": object()}},
])
def test_tenant_ec2_plan_ownership_rejects_malformed_provider_records(instance):
    with patch("autonomy.api.aws_service.get_ec2_instance", return_value={
        "status": "healthy", "instance": instance,
    }), pytest.raises(autonomy_api.HTTPException) as error:
        autonomy_api._require_tenant_ec2_instance(_tenant_request(), "i-123456789")

    assert error.value.status_code == 503
    assert error.value.detail == "EC2 inventory is unavailable"


def test_tenant_ec2_plan_ownership_keeps_missing_and_foreign_resources_hidden():
    for result in (
        {"status": "healthy", "instance": None},
        {"status": "healthy", "instance": {
            "instance_id": "i-123456789", "tags": {"CloudOpsTenantId": "tenant-b"},
        }},
    ):
        with patch("autonomy.api.aws_service.get_ec2_instance", return_value=result):
            with pytest.raises(autonomy_api.HTTPException) as error:
                autonomy_api._require_tenant_ec2_instance(_tenant_request(), "i-123456789")
        assert error.value.status_code == 404


def test_tenant_ec2_plan_ownership_sanitizes_provider_exceptions():
    with patch("autonomy.api.aws_service.get_ec2_instance", side_effect=RuntimeError("private AWS detail")):
        with pytest.raises(autonomy_api.HTTPException) as error:
            autonomy_api._require_tenant_ec2_instance(_tenant_request(), "i-123456789")

    assert error.value.status_code == 503
    assert "private AWS detail" not in error.value.detail


def test_tenant_s3_plan_ownership_accepts_matching_well_formed_resource():
    with patch("autonomy.api.aws_service.get_s3_bucket_tags", return_value={
        "status": "healthy", "bucket": "example-bucket",
        "tags": {"CloudOpsTenantId": "tenant-a"},
    }) as lookup:
        autonomy_api._require_tenant_s3_bucket(_tenant_request(), "example-bucket")

    lookup.assert_called_once_with("example-bucket")


@pytest.mark.parametrize("result", [
    None,
    {"status": "healthy", "tags": []},
    {"status": "healthy", "tags": {"CloudOpsTenantId": object()}},
    {"status": "healthy", "bucket": "other-bucket", "tags": {}},
    {"status": "unexpected", "tags": {}},
    {"status": "unhealthy", "error": "private provider detail"},
])
def test_tenant_s3_plan_ownership_fails_closed_on_malformed_or_unhealthy_results(result):
    with patch("autonomy.api.aws_service.get_s3_bucket_tags", return_value=result):
        with pytest.raises(autonomy_api.HTTPException) as error:
            autonomy_api._require_tenant_s3_bucket(_tenant_request(), "example-bucket")

    assert error.value.status_code == 503
    assert "private provider detail" not in error.value.detail


def test_tenant_s3_plan_ownership_keeps_missing_and_foreign_resources_hidden():
    for result in (
        {"status": "missing", "tags": {}},
        {"status": "healthy", "tags": {"CloudOpsTenantId": "tenant-b"}},
    ):
        with patch("autonomy.api.aws_service.get_s3_bucket_tags", return_value=result):
            with pytest.raises(autonomy_api.HTTPException) as error:
                autonomy_api._require_tenant_s3_bucket(_tenant_request(), "example-bucket")
        assert error.value.status_code == 404


def test_tenant_s3_plan_ownership_sanitizes_provider_exceptions():
    with patch("autonomy.api.aws_service.get_s3_bucket_tags", side_effect=RuntimeError("private AWS detail")):
        with pytest.raises(autonomy_api.HTTPException) as error:
            autonomy_api._require_tenant_s3_bucket(_tenant_request(), "example-bucket")

    assert error.value.status_code == 503
    assert "private AWS detail" not in error.value.detail


@pytest.mark.parametrize(
    ("path", "provider_method", "provider_args"),
    [
        (
            "/autonomy/ec2/instances/i-123456789/plans",
            "get_ec2_insights",
            ("i-123456789",),
        ),
        (
            "/autonomy/s3/buckets/example-bucket/plans",
            "get_s3_bucket_insights",
            ("example-bucket",),
        ),
    ],
)
def test_plan_creation_returns_plan_for_healthy_provider(path, provider_method, provider_args):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner, patch("autonomy.api._plan_response", return_value={"plans": []}) as response:
        getattr(aws, provider_method).return_value = {"status": "healthy", "insights": []}
        planner_method = (
            "plan_from_ec2_insights" if provider_method == "get_ec2_insights"
            else "plan_from_s3_insights"
        )
        getattr(planner, planner_method).return_value = []

        result = client.post(path)

    assert result.status_code == 200
    assert result.json() == {"plans": []}
    if provider_method == "get_ec2_insights":
        aws.get_ec2_insights.assert_called_once_with(*provider_args)
    else:
        aws.get_s3_bucket_insights.assert_called_once_with(
            *provider_args, prefix=None, max_keys=None
        )
    response.assert_called_once()


@pytest.mark.parametrize(
    ("path", "provider_method", "provider_args"),
    [
        (
            "/autonomy/ec2/instances/i-123456789/plans",
            "get_ec2_insights",
            ("i-123456789",),
        ),
        (
            "/autonomy/s3/buckets/example-bucket/plans",
            "get_s3_bucket_insights",
            ("example-bucket",),
        ),
    ],
)
def test_plan_creation_sanitizes_provider_failures_as_service_unavailable(
    path, provider_method, provider_args
):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner, patch("autonomy.api._plan_response") as response:
        getattr(aws, provider_method).return_value = {
            "status": "unhealthy",
            "error": "AccessDenied for account 123456789012",
        }

        result = client.post(path)

    assert result.status_code == 503
    assert result.json() == {"detail": "AWS resource data is unavailable"}
    assert "123456789012" not in result.text
    getattr(aws, provider_method).assert_called_once()
    planner.assert_not_called()
    response.assert_not_called()


@pytest.mark.parametrize(
    ("path", "provider_method"),
    [
        ("/autonomy/ec2/instances/i-123456789/plans", "get_ec2_insights"),
        ("/autonomy/s3/buckets/example-bucket/plans", "get_s3_bucket_insights"),
    ],
)
@pytest.mark.parametrize(
    "provider_result",
    [None, {"status": "healthy"}, {"status": "healthy", "insights": None}],
)
def test_plan_creation_fails_closed_on_malformed_provider_payload(
    path, provider_method, provider_result
):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner:
        getattr(aws, provider_method).return_value = provider_result

        result = client.post(path)

    assert result.status_code == 503
    assert result.json() == {"detail": "AWS resource data is unavailable"}
    planner_method = (
        "plan_from_ec2_insights" if provider_method == "get_ec2_insights"
        else "plan_from_s3_insights"
    )
    getattr(planner, planner_method).assert_not_called()


@pytest.mark.parametrize(
    ("path", "provider_method"),
    [
        ("/autonomy/ec2/instances/i-123456789/plans", "get_ec2_insights"),
        ("/autonomy/s3/buckets/example-bucket/plans", "get_s3_bucket_insights"),
    ],
)
def test_plan_creation_sanitizes_thrown_provider_exception(path, provider_method):
    with patch("autonomy.api.aws_service") as aws, patch(
        "autonomy.api.action_planner"
    ) as planner:
        getattr(aws, provider_method).side_effect = RuntimeError(
            "AccessDenied for account 123456789012"
        )

        result = client.post(path)

    assert result.status_code == 503
    assert result.json() == {"detail": "AWS resource data is unavailable"}
    assert "123456789012" not in result.text
    planner_method = (
        "plan_from_ec2_insights" if provider_method == "get_ec2_insights"
        else "plan_from_s3_insights"
    )
    getattr(planner, planner_method).assert_not_called()


def test_s3_plan_rejects_out_of_range_scan_limit_before_provider_call():
    with patch("autonomy.api.aws_service") as aws:
        result = client.post("/autonomy/s3/buckets/example-bucket/plans?max_keys=1001")

    assert result.status_code == 400
    assert result.json() == {"detail": "max_keys must be between 1 and 1000"}
    aws.get_s3_bucket_insights.assert_not_called()
