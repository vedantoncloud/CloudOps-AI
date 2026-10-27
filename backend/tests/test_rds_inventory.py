from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from auth import AccessControlMiddleware, Principal
from services.aws_service import AWSService


def record(identifier="orders-db", tenant="tenant-a"):
    return {
        "identifier": identifier, "arn": f"arn:aws:rds:us-east-1:123456789012:db:{identifier}",
        "engine": "postgres", "engine_version": "16.1", "status": "available",
        "instance_class": "db.t4g.medium", "storage_gib": 100, "encrypted": True,
        "multi_az": False, "availability_zone": "us-east-1a", "endpoint": "db.example.test",
        "port": 5432, "tags": {"CloudOpsTenantId": tenant},
    }


def test_rds_service_maps_pagination_endpoint_and_tags(monkeypatch):
    class Client:
        def describe_db_instances(self, **kwargs):
            assert kwargs == {"MaxRecords": 20, "Marker": "cursor"}
            return {"DBInstances": [{"DBInstanceIdentifier": "orders-db", "DBInstanceArn": "arn:aws:rds:us-east-1:123456789012:db:orders-db", "Endpoint": {"Address": "db.example.test", "Port": 5432}, "StorageEncrypted": True, "MultiAZ": False, "AllocatedStorage": 100}], "Marker": "next"}
        def list_tags_for_resource(self, **kwargs):
            assert kwargs["ResourceName"].endswith(":db:orders-db")
            return {"TagList": [{"Key": "CloudOpsTenantId", "Value": "tenant-a"}]}
    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Client())
    result = AWSService().get_rds_instances(max_records=20, marker="cursor", region="us-east-1")
    assert result["status"] == "healthy" and result["is_truncated"]
    assert result["instances"][0]["endpoint"] == "db.example.test"
    assert result["instances"][0]["tags"]["CloudOpsTenantId"] == "tenant-a"


def test_rds_service_fails_closed_on_provider_or_malformed_tag_response(monkeypatch):
    class Denied:
        def describe_db_instances(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "private"}}, "DescribeDBInstances")
    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Denied())
    assert AWSService().get_rds_instances()["status"] == "unhealthy"

    class BadTags:
        def describe_db_instances(self, **kwargs):
            return {"DBInstances": [{"DBInstanceIdentifier": "orders-db", "DBInstanceArn": "arn:aws:rds:region:acct:db:orders-db"}]}
        def list_tags_for_resource(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret"}}, "ListTagsForResource")
    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: BadTags())
    assert AWSService().get_rds_instances()["status"] == "unhealthy"


def test_rds_endpoint_validation_authorization_and_tenant_filter(monkeypatch):
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "reader": Principal("alice", "reader", "tenant-a"),
        "operator": Principal("bob", "operator", "tenant-a"),
    })
    calls = []
    monkeypatch.setattr(main.aws_service, "get_rds_instances", lambda **kwargs: calls.append(kwargs) or {
        "service": "rds", "status": "healthy", "instances": [record(), record("foreign-db", "tenant-b")],
        "next_marker": None, "is_truncated": False,
    })
    client = TestClient(app)
    assert client.get("/cloud/aws/rds/instances").status_code == 401
    assert client.get("/cloud/aws/rds/instances?max_records=10", headers={"Authorization": "Bearer reader"}).status_code == 400
    assert calls == []
    response = client.get("/cloud/aws/rds/instances", headers={"Authorization": "Bearer reader"})
    assert response.status_code == 200
    assert [row["identifier"] for row in response.json()["instances"]] == ["orders-db"]
    assert client.post("/cloud/aws/rds/instances", headers={"Authorization": "Bearer reader"}).status_code == 403


def test_rds_endpoint_sanitizes_unavailable_and_malformed_payloads(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main.aws_service, "get_rds_instances", lambda **kwargs: {"status": "unhealthy", "error": "secret"})
    response = client.get("/cloud/aws/rds/instances")
    assert response.status_code == 503 and "secret" not in response.text
    monkeypatch.setattr(main.aws_service, "get_rds_instances", lambda **kwargs: {
        "service": "rds", "status": "healthy", "instances": [record() | {"port": 70000}],
        "next_marker": None, "is_truncated": False,
    })
    assert client.get("/cloud/aws/rds/instances").status_code == 503
