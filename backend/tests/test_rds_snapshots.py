from datetime import datetime, timezone

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from auth import AccessControlMiddleware, Principal
from services.aws_service import AWSService


def snapshot(identifier="orders-db-snapshot", tenant="tenant-a"):
    return {
        "identifier": identifier,
        "arn": f"arn:aws:rds:us-east-1:123456789012:snapshot:{identifier}",
        "db_instance_identifier": "orders-db", "engine": "postgres", "status": "available",
        "snapshot_type": "automated", "storage_gib": 100, "encrypted": True,
        "kms_key_id": "arn:aws:kms:us-east-1:123456789012:key/example",
        "snapshot_create_time": "2026-10-27T00:00:00+00:00",
        "tags": {"CloudOpsTenantId": tenant},
    }


def test_rds_snapshot_service_paginates_maps_metadata_and_tags(monkeypatch):
    class Client:
        def describe_db_snapshots(self, **kwargs):
            assert kwargs == {"MaxRecords": 20, "Marker": "cursor"}
            return {"DBSnapshots": [{
                "DBSnapshotIdentifier": "orders-db-snapshot",
                "DBSnapshotArn": "arn:aws:rds:us-east-1:123456789012:snapshot:orders-db-snapshot",
                "DBInstanceIdentifier": "orders-db", "Engine": "postgres", "Status": "available",
                "SnapshotType": "automated", "AllocatedStorage": 100, "Encrypted": True,
                "KmsKeyId": "key-1", "SnapshotCreateTime": datetime(2026, 10, 27, tzinfo=timezone.utc),
            }], "Marker": "next"}

        def list_tags_for_resource(self, **kwargs):
            assert kwargs["ResourceName"].endswith(":snapshot:orders-db-snapshot")
            return {"TagList": [{"Key": "CloudOpsTenantId", "Value": "tenant-a"}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Client())
    result = AWSService().get_rds_snapshots(max_records=20, marker="cursor", region="us-east-1")
    assert result["status"] == "healthy" and result["next_marker"] == "next"
    assert result["snapshots"][0]["snapshot_create_time"] == "2026-10-27T00:00:00+00:00"
    assert result["snapshots"][0]["tags"]["CloudOpsTenantId"] == "tenant-a"


def test_rds_snapshot_service_fails_closed_on_provider_and_malformed_data(monkeypatch):
    class Denied:
        def describe_db_snapshots(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret"}}, "DescribeDBSnapshots")

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Denied())
    assert AWSService().get_rds_snapshots()["status"] == "unhealthy"

    class Malformed:
        def describe_db_snapshots(self, **kwargs):
            return {"DBSnapshots": [{"DBSnapshotIdentifier": "snapshot"}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Malformed())
    assert AWSService().get_rds_snapshots()["status"] == "unhealthy"

    class DeniedTags:
        def describe_db_snapshots(self, **kwargs):
            return {"DBSnapshots": [{"DBSnapshotIdentifier": "snapshot", "DBSnapshotArn": "arn:aws:rds:region:account:snapshot:snapshot"}]}

        def list_tags_for_resource(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret"}}, "ListTagsForResource")

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: DeniedTags())
    assert AWSService().get_rds_snapshots()["status"] == "unhealthy"


def test_rds_snapshot_api_authorization_validation_tenant_scope_and_failures(monkeypatch):
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "reader": Principal("alice", "reader", "tenant-a"),
        "operator": Principal("bob", "operator", "tenant-a"),
    })
    calls = []
    monkeypatch.setattr(main.aws_service, "get_rds_snapshots", lambda **kwargs: calls.append(kwargs) or {
        "service": "rds", "status": "healthy", "snapshots": [snapshot(), snapshot("foreign", "tenant-b")],
        "next_marker": None, "is_truncated": False,
    })
    client = TestClient(app)
    assert client.get("/cloud/aws/rds/snapshots").status_code == 401
    assert client.get("/cloud/aws/rds/snapshots?max_records=10", headers={"Authorization": "Bearer reader"}).status_code == 400
    assert calls == []
    response = client.get("/cloud/aws/rds/snapshots?marker=cursor", headers={"Authorization": "Bearer reader"})
    assert response.status_code == 200
    assert [row["identifier"] for row in response.json()["snapshots"]] == ["orders-db-snapshot"]
    assert calls[-1] == {"max_records": 100, "marker": "cursor"}
    assert client.post("/cloud/aws/rds/snapshots", headers={"Authorization": "Bearer reader"}).status_code == 403

    monkeypatch.setattr(main.aws_service, "get_rds_snapshots", lambda **kwargs: {
        "service": "rds", "status": "healthy", "snapshots": [],
        "next_marker": None, "is_truncated": False,
    })
    empty = client.get("/cloud/aws/rds/snapshots", headers={"Authorization": "Bearer reader"})
    assert empty.status_code == 200 and empty.json()["snapshots"] == []

    monkeypatch.setattr(main.aws_service, "get_rds_snapshots", lambda **kwargs: {
        "service": "rds", "status": "healthy", "snapshots": [snapshot()],
        "next_marker": "", "is_truncated": True,
    })
    assert client.get("/cloud/aws/rds/snapshots", headers={"Authorization": "Bearer reader"}).status_code == 503

    monkeypatch.setattr(main.aws_service, "get_rds_snapshots", lambda **kwargs: {"status": "unhealthy", "error": "private"})
    failed = client.get("/cloud/aws/rds/snapshots", headers={"Authorization": "Bearer reader"})
    assert failed.status_code == 503 and "private" not in failed.text

    monkeypatch.setattr(main.aws_service, "get_rds_snapshots", lambda **kwargs: {
        "service": "rds", "status": "healthy", "snapshots": [snapshot() | {"encrypted": "yes"}],
        "next_marker": None, "is_truncated": False,
    })
    assert client.get("/cloud/aws/rds/snapshots", headers={"Authorization": "Bearer reader"}).status_code == 503
