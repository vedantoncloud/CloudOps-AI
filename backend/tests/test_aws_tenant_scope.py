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


def tenant_client(monkeypatch):
    monkeypatch.setattr(main, "aws_service", FakeAWSService())
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"token-a": Principal("alice", "reader", "tenant-a")},
    )
    return TestClient(app)


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
