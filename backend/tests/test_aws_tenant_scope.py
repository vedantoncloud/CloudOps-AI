from types import SimpleNamespace
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import main
from auth import AccessControlMiddleware, Principal


class FakeAWSService:
    def __getattr__(self, name):
        if name.startswith("get_ec2_"):
            return lambda *args, **kwargs: {"status": "healthy", "service": "ec2"}
        raise AttributeError(name)

    def get_ec2_metrics(self, instance_id, **kwargs):
        return {
            "service": "ec2", "status": "healthy", "instance_id": instance_id,
            "cpu": {}, "network": {}, "instance_status": {},
        }

    def get_ec2_instance_status(self, instance_id, **kwargs):
        return {
            "service": "ec2", "status": "healthy", "instance_id": instance_id,
            "instance_status": None, "system_status": None, "state": None, "events": [],
        }

    def get_ec2_instances(self, state=None, tag=None, max_results=None, next_token=None, name=None, **filters):
        if next_token:
            return {"service": "ec2", "status": "healthy", "instances": [], "next_token": None}
        return {
            "service": "ec2",
            "status": "healthy",
            "instances": [
                {"instance_id": "i-aaaaaaaa", "state": "running", "tags": {"CloudOpsTenantId": "tenant-a"}},
                {"instance_id": "i-bbbbbbbb", "state": "stopped", "tags": {"CloudOpsTenantId": "tenant-b"}},
                {"instance_id": "i-cccccccc", "state": "running", "tags": {}},
            ],
        }

    def get_ec2_instance(self, instance_id):
        instances = {
            item["instance_id"]: item
            for item in self.get_ec2_instances()["instances"]
        }
        return {"status": "healthy", "instance": instances.get(instance_id)}

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

    def get_s3_buckets(self, max_buckets=1000, continuation_token=None):
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
        if bucket_name == "untagged":
            return {"status": "healthy", "tags": {}}
        if bucket_name not in tenants:
            return {"status": "missing", "tags": {}}
        return {"status": "healthy", "tags": {"CloudOpsTenantId": tenants[bucket_name]}}

    def get_s3_bucket_details(self, bucket_name):
        return {"status": "healthy", "bucket": bucket_name, "region": "us-east-1"}

    def get_s3_object_metadata(self, bucket_name, object_key, version_id=None):
        return {"status": "healthy", "bucket": bucket_name, "object": {"key": object_key, "version_id": version_id}}

    def create_s3_object_download_url(self, bucket_name, object_key):
        return {
            "service": "s3",
            "status": "healthy",
            "bucket": bucket_name,
            "key": object_key,
            "url": "https://signed.example/download",
            "expires_in": 300,
        }


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


def test_ec2_network_filter_preserves_tenant_scoping(monkeypatch):
    client = tenant_client(monkeypatch)
    response = client.get(
        "/cloud/aws/ec2/instances?vpc_id=vpc-12345678&subnet_id=subnet-12345678",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert [item["instance_id"] for item in response.json()["instances"]] == [
        "i-aaaaaaaa"
    ]


def test_ec2_volume_details_verify_instance_tenant_before_provider_lookup(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    calls = []
    original_instance_lookup = service.get_ec2_instance
    service.get_ec2_instance = lambda instance_id, **kwargs: original_instance_lookup(instance_id)
    service.get_ec2_instance_volumes = lambda instance_id, **kwargs: (
        calls.append((instance_id, kwargs)) or {
            "service": "ec2", "status": "healthy", "instance_id": instance_id,
            "volumes": [{"volume_id": "vol-a", "encrypted": True}],
        }
    )
    headers = {"Authorization": "Bearer token-a"}

    owned = client.get("/cloud/aws/ec2/instances/i-aaaaaaaa/volumes?region=eu-west-1", headers=headers)
    foreign = client.get("/cloud/aws/ec2/instances/i-bbbbbbbb/volumes", headers=headers)

    assert owned.status_code == 200
    assert owned.json()["volumes"][0]["encrypted"] is True
    assert calls == [("i-aaaaaaaa", {"region": "eu-west-1"})]
    assert foreign.status_code == 404


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


@pytest.mark.parametrize(
    "provider_result",
    [None, {"service": "ec2", "status": "connected"}],
)
def test_aws_service_health_rejects_malformed_provider_results(monkeypatch, provider_result):
    client = tenant_client(monkeypatch)
    monkeypatch.setattr(main.aws_service, "get_service_health", lambda _name: provider_result)

    response = client.get(
        "/cloud/aws/services/ec2", headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS service health is unavailable"}


def test_aws_service_health_sanitizes_provider_exceptions(monkeypatch):
    client = tenant_client(monkeypatch)

    def fail(_name):
        raise RuntimeError("secret account and request diagnostics")

    monkeypatch.setattr(main.aws_service, "get_service_health", fail)
    response = client.get(
        "/cloud/aws/services/ec2", headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS service health is unavailable"}
    assert "secret" not in response.text


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


def test_ec2_summary_counts_tenant_instances_across_all_pages(monkeypatch):
    service = FakeAWSService()
    calls = []

    def page(state=None, tag=None, max_results=None, next_token=None, name=None, **filters):
        calls.append((next_token, filters.get("region")))
        if next_token is None:
            return {
                "service": "ec2", "status": "healthy",
                "instances": [{"state": "running", "tags": {"CloudOpsTenantId": "tenant-a"}}],
                "next_token": "page-2",
            }
        return {
            "service": "ec2", "status": "healthy",
            "instances": [
                {"state": "stopped", "tags": {"CloudOpsTenantId": "tenant-a"}},
                {"state": "running", "tags": {"CloudOpsTenantId": "tenant-b"}},
            ],
            "next_token": None,
        }

    service.get_ec2_instances = page
    client = tenant_client(monkeypatch)
    monkeypatch.setattr(main, "aws_service", service)
    response = client.get(
        "/cloud/aws/ec2/summary?region=eu-west-3", headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "service": "ec2", "status": "healthy", "total_instances": 2,
        "running_instances": 1, "stopped_instances": 1,
        "region": "eu-west-3",
    }
    assert calls == [(None, "eu-west-3"), ("page-2", "eu-west-3")]


@pytest.mark.parametrize("path,method", [
    ("/cloud/aws/ec2/instances", "get_ec2_instances"),
    ("/cloud/aws/ec2/summary", "get_ec2_instances"),
    ("/cloud/aws/s3/buckets", "get_s3_buckets"),
])
def test_core_inventory_endpoints_return_sanitized_503_when_aws_is_unavailable(monkeypatch, path, method):
    app_client = tenant_client(monkeypatch)
    service = main.aws_service

    def unavailable(*args, **kwargs):
        return {"status": "unhealthy", "error": "private AWS account diagnostic"}
    setattr(service, method, unavailable)

    response = app_client.get(path, headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "private AWS" not in response.text


def test_unscoped_ec2_summary_returns_sanitized_503_when_aws_is_unavailable(monkeypatch):
    app_client = tenant_client(monkeypatch)
    service = main.aws_service
    service.get_ec2_summary = lambda: {
        "status": "unhealthy", "error": "private AWS account diagnostic"
    }

    with pytest.raises(HTTPException) as error:
        main.aws_ec2_summary(SimpleNamespace(state=SimpleNamespace(tenant_scoped=False)))

    assert error.value.status_code == 503
    assert error.value.detail == "AWS resource data is unavailable"


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
    monkeypatch.setattr(service, "get_ec2_instance", lambda instance_id: {"status": "unhealthy"})

    response = client.get(
        "/cloud/aws/ec2/instances/i-aaaaaaaa",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_ec2_instance_details_finds_owned_instance_beyond_inventory_page(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    instance = {
        "instance_id": "i-dddddddd",
        "state": "running",
        "instance_type": "t3.small",
        "tags": {"CloudOpsTenantId": "tenant-a"},
    }
    monkeypatch.setattr(
        service,
        "get_ec2_instance",
        lambda instance_id: {"status": "healthy", "instance": instance},
    )
    monkeypatch.setattr(
        service,
        "get_ec2_instances",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("detail must use direct lookup")),
    )

    response = client.get(
        "/cloud/aws/ec2/instances/i-dddddddd",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert response.json()["instance"] == instance


def test_tenant_ec2_metric_lookup_finds_owned_instance_outside_first_inventory_page(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    monkeypatch.setattr(
        service,
        "get_ec2_instances",
        lambda *args, **kwargs: {"status": "healthy", "instances": [], "is_truncated": True, "next_token": "page-2"},
    )
    monkeypatch.setattr(
        service,
        "get_ec2_instance",
        lambda instance_id: {
            "status": "healthy",
            "instance": {"instance_id": instance_id, "tags": {"CloudOpsTenantId": "tenant-a"}},
        },
    )

    response = client.get(
        "/cloud/aws/ec2/instances/i-dddddddd/metrics",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200


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


@pytest.mark.parametrize("path,method", [
    ("/cloud/aws/ec2/efficiency-insights", "get_ec2_efficiency_insights"),
    ("/cloud/aws/ec2/cost-insights", "get_ec2_cost_insights"),
    ("/cloud/aws/ec2/rightsizing-insights", "get_ec2_rightsizing_insights"),
    ("/cloud/aws/ec2/security-insights", "get_ec2_security_insights"),
])
def test_aggregate_ec2_insights_include_owned_instances_from_every_page(monkeypatch, path, method):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    calls = []
    pages = {
        None: {
            "status": "healthy", "instances": [
                {"instance_id": "i-first", "tags": {"CloudOpsTenantId": "tenant-a"}},
                {"instance_id": "i-foreign", "tags": {"CloudOpsTenantId": "tenant-b"}},
            ], "next_token": "page-2",
        },
        "page-2": {
            "status": "healthy", "instances": [
                {"instance_id": "i-second", "tags": {"CloudOpsTenantId": "tenant-a"}},
                {"instance_id": "i-untagged", "tags": {}},
            ], "next_token": None,
        },
    }

    def get_page(state=None, tag=None, max_results=None, next_token=None, name=None):
        calls.append(next_token)
        return pages[next_token]

    seen = []
    monkeypatch.setattr(service, "get_ec2_instances", get_page)
    monkeypatch.setattr(service, method, lambda instances: seen.extend(instances) or {
        "status": "healthy", "instance_count": len(instances), "insights": [],
    })

    response = client.get(path, headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 200
    assert calls == [None, "page-2"]
    assert [item["instance_id"] for item in seen] == ["i-first", "i-second"]
    assert response.json()["instance_count"] == 2


@pytest.mark.parametrize("path,method", [
    ("/cloud/aws/ec2/efficiency-insights", "get_ec2_efficiency_insights"),
    ("/cloud/aws/ec2/cost-insights", "get_ec2_cost_insights"),
    ("/cloud/aws/ec2/rightsizing-insights", "get_ec2_rightsizing_insights"),
    ("/cloud/aws/ec2/security-insights", "get_ec2_security_insights"),
])
def test_aggregate_ec2_insights_do_not_run_on_partial_inventory(monkeypatch, path, method):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    def get_page(state=None, tag=None, max_results=None, next_token=None, name=None):
        if next_token is None:
            return {
                "status": "healthy", "instances": [
                    {"instance_id": "i-first", "tags": {"CloudOpsTenantId": "tenant-a"}},
                ], "next_token": "page-2",
            }
        return {"status": "unhealthy", "error": "AWS unavailable", "instances": []}

    monkeypatch.setattr(service, "get_ec2_instances", get_page)
    monkeypatch.setattr(service, method, lambda **kwargs: pytest.fail("partial inventory must not be analyzed"))

    response = client.get(path, headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


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


@pytest.mark.parametrize("suffix", ["cpu", "network", "status"])
def test_individual_ec2_routes_reject_malformed_ids_before_provider_calls(monkeypatch, suffix):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    monkeypatch.setattr(
        service,
        "get_ec2_instance",
        lambda *_args, **_kwargs: pytest.fail("invalid ID must not reach ownership lookup"),
    )
    monkeypatch.setattr(
        service,
        {
            "cpu": "get_ec2_cpu_utilization",
            "network": "get_ec2_network_utilization",
            "status": "get_ec2_instance_status",
        }[suffix],
        lambda *_args, **_kwargs: pytest.fail("invalid ID must not reach AWS"),
    )

    response = client.get(
        f"/cloud/aws/ec2/instances/not-an-instance/{suffix}",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid EC2 instance ID"}


def test_s3_inventory_hides_foreign_and_untagged_buckets(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/s3/buckets", headers={"Authorization": "Bearer token-a"}
    )

    assert response.status_code == 200
    assert response.json()["buckets"] == [{"name": "owned"}]


def test_s3_inventory_fills_tenant_page_across_mixed_aws_pages(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    calls = []
    pages = {
        None: {"status": "healthy", "buckets": [{"name": "foreign"}],
               "is_truncated": True, "next_continuation_token": "page-2"},
        "page-2": {"status": "healthy", "buckets": [{"name": "owned"}],
                   "is_truncated": True, "next_continuation_token": "page-3"},
        "page-3": {"status": "healthy", "buckets": [{"name": "owned-2"}],
                   "is_truncated": False, "next_continuation_token": None},
    }

    def list_buckets(max_buckets, continuation_token):
        calls.append((max_buckets, continuation_token))
        return pages[continuation_token]

    monkeypatch.setattr(service, "get_s3_buckets", list_buckets)
    monkeypatch.setattr(service, "get_s3_bucket_tags", lambda bucket: {
        "status": "healthy", "tags": {"CloudOpsTenantId": (
            "tenant-b" if bucket == "foreign" else "tenant-a"
        )}
    })
    response = client.get(
        "/cloud/aws/s3/buckets?max_buckets=2",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert [bucket["name"] for bucket in response.json()["buckets"]] == ["owned", "owned-2"]
    assert response.json()["is_truncated"] is False
    assert calls == [(2, None), (2, "page-2"), (1, "page-3")]


def test_s3_inventory_fails_closed_if_a_later_page_is_unavailable(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    calls = []

    def list_buckets(max_buckets, continuation_token):
        calls.append(continuation_token)
        if continuation_token is None:
            return {"status": "healthy", "buckets": [{"name": "foreign"}],
                    "is_truncated": True, "next_continuation_token": "page-2"}
        return {"status": "unhealthy", "error": "private AWS diagnostic"}

    monkeypatch.setattr(service, "get_s3_buckets", list_buckets)
    response = client.get(
        "/cloud/aws/s3/buckets?max_buckets=2",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "S3 inventory is unavailable"}
    assert calls == [None, "page-2"]


def test_s3_inventory_rejects_repeated_provider_cursor(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    monkeypatch.setattr(service, "get_s3_buckets", lambda *_args: {
        "status": "healthy", "buckets": [{"name": "foreign"}],
        "is_truncated": True, "next_continuation_token": "same-page",
    })

    response = client.get(
        "/cloud/aws/s3/buckets?max_buckets=2",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "S3 inventory pagination is unavailable"}


def test_s3_inventory_reports_ownership_verification_outage(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    monkeypatch.setattr(
        service, "get_s3_bucket_tags",
        lambda _bucket: {"status": "unhealthy", "error": "private AWS diagnostic"},
    )

    response = client.get("/cloud/aws/s3/buckets", headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": "S3 ownership verification is unavailable"}


@pytest.mark.parametrize("failure_page", [1, 2])
def test_s3_inventory_sanitizes_provider_exceptions_on_every_page(monkeypatch, failure_page):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    calls = []

    def list_buckets(_limit, cursor=None, **_kwargs):
        calls.append(cursor)
        if len(calls) == failure_page:
            raise RuntimeError("private AWS diagnostic for account 123456789012")
        return {
            "status": "healthy",
            "buckets": [{"name": "foreign"}],
            "is_truncated": True,
            "next_continuation_token": "page-2",
        }

    monkeypatch.setattr(service, "get_s3_buckets", list_buckets)
    response = client.get(
        "/cloud/aws/s3/buckets?max_buckets=2",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "123456789012" not in response.text
    assert calls == ([None] if failure_page == 1 else [None, "page-2"])


@pytest.mark.parametrize("ownership_result", [None, {"status": "healthy", "tags": []}])
def test_s3_inventory_fails_closed_on_malformed_ownership_response(monkeypatch, ownership_result):
    client = tenant_client(monkeypatch)
    monkeypatch.setattr(main.aws_service, "get_s3_bucket_tags", lambda _bucket: ownership_result)

    response = client.get("/cloud/aws/s3/buckets", headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": "S3 ownership verification is unavailable"}


def test_s3_inventory_sanitizes_ownership_lookup_exception(monkeypatch):
    client = tenant_client(monkeypatch)

    def fail(_bucket):
        raise RuntimeError("private AWS diagnostic for account 123456789012")

    monkeypatch.setattr(main.aws_service, "get_s3_bucket_tags", fail)
    response = client.get("/cloud/aws/s3/buckets", headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": "S3 ownership verification is unavailable"}
    assert "123456789012" not in response.text


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


def test_s3_detail_reports_ownership_verification_outage_without_leaking_provider_error(monkeypatch):
    client = tenant_client(monkeypatch)
    service = main.aws_service
    monkeypatch.setattr(
        service, "get_s3_bucket_tags",
        lambda _bucket: {"status": "unhealthy", "error": "access denied for 123456789012"},
    )

    response = client.get("/cloud/aws/s3/buckets/owned", headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": "S3 ownership verification is unavailable"}


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

    historical = client.get(
        "/cloud/aws/s3/buckets/owned/objects/metadata",
        params={"key": "reports/annual report.csv", "version_id": "v/1"},
        headers=headers,
    )
    assert historical.status_code == 200
    assert historical.json()["object"]["version_id"] == "v/1"

    empty_version = client.get(
        "/cloud/aws/s3/buckets/owned/objects/metadata",
        params={"key": "reports/annual report.csv", "version_id": ""},
        headers=headers,
    )
    assert empty_version.status_code == 400

    foreign = client.get(
        "/cloud/aws/s3/buckets/foreign/objects/metadata",
        params={"key": "reports/annual report.csv"},
        headers=headers,
    )
    assert foreign.status_code == 404


def test_s3_object_download_is_tenant_scoped_and_preserves_nested_key(monkeypatch):
    client = tenant_client(monkeypatch)
    headers = {"Authorization": "Bearer token-a"}
    response = client.get(
        "/cloud/aws/s3/buckets/owned/objects/download",
        params={"key": "reports/annual report.csv"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["key"] == "reports/annual report.csv"
    assert response.json()["expires_in"] == 300

    foreign = client.get(
        "/cloud/aws/s3/buckets/foreign/objects/download",
        params={"key": "reports/annual report.csv"},
        headers=headers,
    )
    assert foreign.status_code == 404
    assert foreign.json() == {"detail": "S3 bucket not found"}


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


def test_s3_plan_generation_reports_ownership_verification_outage(monkeypatch):
    client = tenant_client(monkeypatch)
    service = FakeAWSService()
    monkeypatch.setattr("autonomy.api.aws_service", service)
    monkeypatch.setattr(
        service, "get_s3_bucket_tags",
        lambda _bucket: {"status": "unhealthy", "error": "private AWS diagnostic"},
    )

    response = client.post(
        "/autonomy/s3/buckets/owned/plans",
        headers={"Authorization": "Bearer operator-a"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "S3 ownership verification is unavailable"}


@pytest.mark.parametrize(
    ("path", "method", "detail"),
    [
        (
            "/autonomy/ec2/instances/i-aaaaaaaa/plans",
            "get_ec2_instance",
            "AWS resource data is unavailable",
        ),
        (
            "/autonomy/s3/buckets/owned/plans",
            "get_s3_bucket_tags",
            "S3 ownership verification is unavailable",
        ),
    ],
)
def test_plan_generation_sanitizes_ownership_lookup_exceptions(
    monkeypatch, path, method, detail
):
    client = tenant_client(monkeypatch)
    service = FakeAWSService()

    def fail(*_args, **_kwargs):
        raise RuntimeError("private AWS diagnostic for account 123456789012")

    monkeypatch.setattr("autonomy.api.aws_service", service)
    monkeypatch.setattr(service, method, fail)

    response = client.post(path, headers={"Authorization": "Bearer operator-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": detail}
    assert "123456789012" not in response.text


@pytest.mark.parametrize(
    ("path", "method", "result", "detail"),
    [
        (
            "/autonomy/ec2/instances/i-aaaaaaaa/plans",
            "get_ec2_instance",
            None,
            "EC2 inventory is unavailable",
        ),
        (
            "/autonomy/s3/buckets/owned/plans",
            "get_s3_bucket_tags",
            None,
            "S3 ownership verification is unavailable",
        ),
    ],
)
def test_plan_generation_fails_closed_on_malformed_ownership_response(
    monkeypatch, path, method, result, detail
):
    client = tenant_client(monkeypatch)
    service = FakeAWSService()
    monkeypatch.setattr("autonomy.api.aws_service", service)
    monkeypatch.setattr(service, method, lambda *_args, **_kwargs: result)

    response = client.post(path, headers={"Authorization": "Bearer operator-a"})

    assert response.status_code == 503
    assert response.json() == {"detail": detail}


def test_ec2_plan_generation_finds_owned_instance_beyond_inventory_page(monkeypatch):
    client = tenant_client(monkeypatch)
    service = FakeAWSService()
    monkeypatch.setattr("autonomy.api.aws_service", service)
    instance_id = "i-dddddddd"
    monkeypatch.setattr(
        service,
        "get_ec2_instances",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("plan ownership must use a direct instance lookup")
        ),
    )
    monkeypatch.setattr(
        service,
        "get_ec2_instance",
        lambda requested_id: {
            "status": "healthy",
            "instance": {
                "instance_id": requested_id,
                "tags": {"CloudOpsTenantId": "tenant-a"},
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_ec2_insights",
        lambda requested_id: {"status": "healthy", "insights": []},
    )

    response = client.post(
        f"/autonomy/ec2/instances/{instance_id}/plans",
        headers={"Authorization": "Bearer operator-a"},
    )

    assert response.status_code == 200
    assert response.json()["plan_count"] == 0


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


def test_ec2_inventory_page_is_tenant_filtered_and_cursor_is_forwarded(monkeypatch):
    client = tenant_client(monkeypatch)
    calls = []

    def page(state=None, tag=None, max_results=None, next_token=None, name=None):
        calls.append((max_results, next_token))
        return {
            "status": "healthy",
            "instances": [
                {"instance_id": "i-aaaaaaaa", "tags": {"CloudOpsTenantId": "tenant-a"}},
                {"instance_id": "i-bbbbbbbb", "tags": {"CloudOpsTenantId": "tenant-b"}},
            ],
            "is_truncated": True,
            "next_token": "opaque-next",
        }

    monkeypatch.setattr(main.aws_service, "get_ec2_instances", page)
    response = client.get(
        "/cloud/aws/ec2/instances?max_results=100&next_token=opaque-prior",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert [item["instance_id"] for item in response.json()["instances"]] == ["i-aaaaaaaa"]
    assert response.json()["next_token"] == "opaque-next"
    assert calls == [(100, "opaque-prior")]


def test_ec2_inventory_page_size_is_bounded(monkeypatch):
    response = tenant_client(monkeypatch).get("/cloud/aws/ec2/instances?max_results=1001", headers={"Authorization": "Bearer token-a"})
    assert response.status_code == 400
    assert response.json()["detail"] == "max_results must be between 5 and 1000"
