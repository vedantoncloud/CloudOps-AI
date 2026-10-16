from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import main
from auth import AccessControlMiddleware, Principal


class FakeAWSService:
    def __getattr__(self, name):
        if name.startswith("get_ec2_"):
            return lambda *args, **kwargs: {"status": "healthy", "service": "ec2"}
        raise AttributeError(name)

    def get_ec2_instances(self, state=None, tag=None):
        return {
            "service": "ec2",
            "status": "healthy",
            "instances": [
                {"instance_id": "i-aaaaaaaa", "state": "running", "tags": {"CloudOpsTenantId": "tenant-a"}},
                {"instance_id": "i-bbbbbbbb", "state": "stopped", "tags": {"CloudOpsTenantId": "tenant-b"}},
                {"instance_id": "i-cccccccc", "state": "running", "tags": {}},
            ],
        }

    def get_ec2_summary(self):
        raise AssertionError("tenant summary must be computed from scoped inventory")

    def get_status(self):
        return {
            "provider": "AWS",
            "status": "connected",
            "account_id": "123456789012",
            "arn": "arn:aws:iam::123456789012:user/cloudops",
            "services": {"ec2": {"status": "healthy"}},
            "message": "AWS services are healthy",
            "error": "internal AWS diagnostic",
        }

    def get_service_health(self, service_name):
        return {
            "service": service_name,
            "status": "unhealthy",
            "error": "internal AWS diagnostic for account 123456789012",
        }

    def get_s3_buckets(self):
        return {
            "service": "s3",
            "status": "healthy",
            "buckets": [
                {"name": "owned"},
                {"name": "foreign"},
                {"name": "untagged"},
            ],
        }

    def get_s3_bucket_tags(self, bucket_name):
        tenants = {"owned": "tenant-a", "foreign": "tenant-b"}
        if bucket_name not in tenants:
            return {"status": "unhealthy", "error": "tags unavailable"}
        return {"status": "healthy", "tags": {"CloudOpsTenantId": tenants[bucket_name]}}

    def get_s3_bucket_details(self, bucket_name):
        return {"status": "healthy", "bucket": bucket_name}

    def get_s3_object_metadata(self, bucket_name, object_key):
        return {"status": "healthy", "bucket": bucket_name, "object": {"key": object_key}}


def tenant_client(monkeypatch):
    monkeypatch.setattr(main, "aws_service", FakeAWSService())
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={
            "token-a": Principal("alice", "reader", "tenant-a"),
            "operator-a": Principal("bob", "operator", "tenant-a"),
            "admin-a": Principal("dana", "admin", "tenant-a"),
        },
    )
    return TestClient(app)


def test_aws_status_hides_shared_account_identity_and_raw_errors_from_tenant(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/status", headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "AWS",
        "status": "connected",
        "services": {"ec2": {"status": "healthy"}},
        "message": "AWS services are healthy",
    }


def test_aws_status_retains_full_diagnostics_for_admin(monkeypatch):
    client = tenant_client(monkeypatch)
    response = client.get(
        "/cloud/aws/status", headers={"Authorization": "Bearer admin-a"}
    )

    assert response.status_code == 200
    assert response.json()["account_id"] == "123456789012"
    assert response.json()["arn"] == "arn:aws:iam::123456789012:user/cloudops"


def test_aws_service_health_hides_raw_errors_from_tenant(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/services/ec2", headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 200
    assert response.json() == {"service": "ec2", "status": "unhealthy"}


def test_aws_service_health_retains_diagnostics_for_admin(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/services/ec2", headers={"Authorization": "Bearer admin-a"}
    )

    assert response.status_code == 200
    assert "123456789012" in response.json()["error"]


def test_ec2_inventory_hides_other_tenants_and_untagged_instances(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/ec2/instances",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert [item["instance_id"] for item in response.json()["instances"]] == ["i-aaaaaaaa"]


def test_ec2_summary_counts_only_the_authenticated_tenants_instances(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/ec2/summary",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "service": "ec2",
        "status": "healthy",
        "total_instances": 1,
        "running_instances": 1,
        "stopped_instances": 0,
    }


def test_ec2_instance_details_returns_only_owned_inventory_record(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/ec2/instances/i-aaaaaaaa",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "service": "ec2",
        "status": "healthy",
        "instance": {
            "instance_id": "i-aaaaaaaa",
            "state": "running",
            "tags": {"CloudOpsTenantId": "tenant-a"},
        },
    }


@pytest.mark.parametrize("instance_id", ["i-bbbbbbbb", "i-cccccccc", "i-dddddddd"])
def test_ec2_instance_details_hides_foreign_untagged_and_missing_records(monkeypatch, instance_id):
    response = tenant_client(monkeypatch).get(
        f"/cloud/aws/ec2/instances/{instance_id}",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "EC2 instance not found"}


def test_ec2_instance_details_reports_inventory_unavailable(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    monkeypatch.setattr(service, "get_ec2_instances", lambda *args: {"status": "unhealthy"})

    response = client.get(
        "/cloud/aws/ec2/instances/i-aaaaaaaa",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "EC2 inventory is unavailable"}


@pytest.mark.parametrize("path,method", [
    ("/cloud/aws/ec2/efficiency-insights", "get_ec2_efficiency_insights"),
    ("/cloud/aws/ec2/cost-insights", "get_ec2_cost_insights"),
    ("/cloud/aws/ec2/rightsizing-insights", "get_ec2_rightsizing_insights"),
    ("/cloud/aws/ec2/security-insights", "get_ec2_security_insights"),
])
def test_aggregate_ec2_insights_analyze_only_authenticated_tenant_instances(monkeypatch, path, method):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    seen = []
    monkeypatch.setattr(
        service,
        method,
        lambda instances: seen.extend(instances) or {
            "service": "ec2", "status": "healthy", "instance_count": len(instances),
            "insight_count": 0, "insights": [],
        },
    )
    response = client.get(path, headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 200
    assert [item["instance_id"] for item in seen] == ["i-aaaaaaaa"]
    assert response.json()["instance_count"] == 1


@pytest.mark.parametrize("path", [
    "/cloud/aws/ec2/instances/i-bbbbbbbb/insights",
    "/cloud/aws/ec2/instances/i-bbbbbbbb/cpu",
    "/cloud/aws/ec2/instances/i-bbbbbbbb/network",
    "/cloud/aws/ec2/instances/i-bbbbbbbb/status",
    "/cloud/aws/ec2/instances/i-bbbbbbbb/metrics",
    "/cloud/aws/ec2/instances/i-cccccccc/status",
])
def test_individual_ec2_routes_hide_foreign_and_untagged_instances(monkeypatch, path):
    response = tenant_client(monkeypatch).get(
        path, headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "EC2 instance not found"}


def test_individual_ec2_route_allows_owned_instance(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/ec2/instances/i-aaaaaaaa/status",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200


def test_s3_inventory_hides_foreign_and_untagged_buckets(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/s3/buckets", headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 200
    assert response.json()["buckets"] == [{"name": "owned"}]


@pytest.mark.parametrize("bucket", ["foreign", "untagged", "missing"])
@pytest.mark.parametrize("suffix", ["", "/objects", "/security-insights"])
def test_s3_routes_hide_foreign_untagged_and_missing_buckets(monkeypatch, bucket, suffix):
    response = tenant_client(monkeypatch).get(
        f"/cloud/aws/s3/buckets/{bucket}{suffix}",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "S3 bucket not found"}


def test_s3_route_allows_owned_bucket(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/s3/buckets/owned",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200


def test_s3_object_metadata_is_tenant_scoped_and_preserves_nested_key(monkeypatch):
    client = tenant_client(monkeypatch)
    headers = {"Authorization": "Bearer token-a"}
    response = client.get(
        "/cloud/aws/s3/buckets/owned/objects/metadata",
        params={"key": "reports/annual report.csv"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["object"]["key"] == "reports/annual report.csv"

    foreign = client.get(
        "/cloud/aws/s3/buckets/foreign/objects/metadata",
        params={"key": "reports/annual report.csv"},
        headers=headers,
    )
    assert foreign.status_code == 404


def test_ec2_plan_generation_hides_foreign_instances(monkeypatch):
    client = tenant_client(monkeypatch)
    service = FakeAWSService()
    monkeypatch.setattr("autonomy.api.aws_service", service)
    called = []
    monkeypatch.setattr(service, "get_ec2_insights", lambda instance_id: called.append(instance_id))

    response = client.post(
        "/autonomy/ec2/instances/i-bbbbbbbb/plans",
        headers={"Authorization": "Bearer operator-a"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "EC2 instance not found"}
    assert called == []


@pytest.mark.parametrize("bucket", ["foreign", "untagged", "missing"])
def test_s3_plan_generation_hides_unowned_buckets(monkeypatch, bucket):
    client = tenant_client(monkeypatch)
    service = FakeAWSService()
    monkeypatch.setattr("autonomy.api.aws_service", service)
    called = []
    monkeypatch.setattr(
        service, "get_s3_bucket_insights",
        lambda bucket_name, **kwargs: called.append(bucket_name),
        raising=False,
    )

    response = client.post(
        f"/autonomy/s3/buckets/{bucket}/plans",
        headers={"Authorization": "Bearer operator-a"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "S3 bucket not found"}
    assert called == []


def test_plan_generation_allows_tenant_owned_s3_bucket(monkeypatch):
    client = tenant_client(monkeypatch)
    service = FakeAWSService()
    monkeypatch.setattr("autonomy.api.aws_service", service)
    monkeypatch.setattr(
        service, "get_s3_bucket_insights",
        lambda bucket_name, **kwargs: {"status": "healthy", "insights": []},
        raising=False,
    )

    response = client.post(
        "/autonomy/s3/buckets/owned/plans",
        headers={"Authorization": "Bearer operator-a"},
    )

    assert response.status_code == 200
    assert response.json()["plan_count"] == 0

@pytest.mark.parametrize("path", [
    "/autonomy/ec2/instances/i-aaaaaaaa/plans",
    "/autonomy/s3/buckets/owned/plans",
])
def test_plan_generation_requires_operator_and_uses_post(monkeypatch, path):
    client = tenant_client(monkeypatch)
    headers = {"Authorization": "Bearer operator-a"}

    assert client.get(path, headers=headers).status_code == 405
    assert client.post(path, headers={"Authorization": "Bearer token-a"}).status_code == 403
