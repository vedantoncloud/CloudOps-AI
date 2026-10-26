from datetime import datetime, timezone

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from auth import AccessControlMiddleware, Principal
from services.aws_service import AWSService


def snapshot(snapshot_id="snap-12345678", tenant="tenant-a"):
    return {
        "snapshot_id": snapshot_id, "volume_id": "vol-12345678", "state": "completed",
        "size_gib": 20, "encrypted": True, "kms_key_id": "key-1", "description": "backup",
        "start_time": "2026-01-01T00:00:00+00:00", "tags": {"CloudOpsTenantId": tenant},
    }


def test_snapshot_service_uses_account_scope_and_maps_page(monkeypatch):
    class Client:
        def describe_snapshots(self, **kwargs):
            assert kwargs == {"OwnerIds": ["self"], "MaxResults": 5, "NextToken": "cursor"}
            return {"Snapshots": [{"SnapshotId": "snap-12345678", "VolumeId": "vol-12345678", "State": "completed", "VolumeSize": 20, "Encrypted": True, "KmsKeyId": "key-1", "Description": "backup", "StartTime": datetime(2026, 1, 1, tzinfo=timezone.utc), "Tags": [{"Key": "CloudOpsTenantId", "Value": "tenant-a"}]}], "NextToken": "next"}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Client())
    result = AWSService().get_ec2_snapshots(max_results=5, next_token="cursor", region="us-east-1")
    assert result["status"] == "healthy"
    assert result["snapshots"][0]["start_time"] == "2026-01-01T00:00:00+00:00"
    assert result["is_truncated"] and result["next_token"] == "next"


def test_snapshot_service_maps_provider_and_malformed_responses(monkeypatch):
    class Broken:
        def describe_snapshots(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret"}}, "DescribeSnapshots")

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Broken())
    assert AWSService().get_ec2_snapshots()["status"] == "unhealthy"

    class Malformed:
        def describe_snapshots(self, **kwargs):
            return {"Snapshots": [{"SnapshotId": "snap-12345678", "Tags": "bad"}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Malformed())
    assert AWSService().get_ec2_snapshots()["status"] == "unhealthy"

    class InvalidTimestamp:
        def describe_snapshots(self, **kwargs):
            return {"Snapshots": [{"SnapshotId": "snap-12345678", "StartTime": "not-a-date"}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: InvalidTimestamp())
    assert AWSService().get_ec2_snapshots()["status"] == "unhealthy"


def test_snapshot_endpoint_validates_input_and_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(main.aws_service, "get_ec2_snapshots", lambda **kwargs: calls.append(kwargs) or {
        "service": "ec2", "status": "healthy", "snapshots": [], "next_token": None, "is_truncated": False,
    })
    client = TestClient(main.app)
    assert client.get("/cloud/aws/ec2/snapshots?region=bad").status_code == 400
    assert client.get("/cloud/aws/ec2/snapshots?max_results=2").status_code == 400
    assert calls == []
    monkeypatch.setattr(main.aws_service, "get_ec2_snapshots", lambda **kwargs: {
        "service": "ec2", "status": "healthy", "snapshots": [snapshot()],
        "next_token": "next", "is_truncated": False,
    })
    response = client.get("/cloud/aws/ec2/snapshots")
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_snapshot_endpoint_auth_tenant_scope_and_empty_page(monkeypatch):
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "reader": Principal("alice", "reader", "tenant-a"),
    })
    monkeypatch.setattr(main.aws_service, "get_ec2_snapshots", lambda **kwargs: {
        "service": "ec2", "status": "healthy",
        "snapshots": [snapshot(), snapshot("snap-87654321", "tenant-b")],
        "next_token": None, "is_truncated": False,
    })
    client = TestClient(app)
    assert client.get("/cloud/aws/ec2/snapshots").status_code == 401
    response = client.get("/cloud/aws/ec2/snapshots", headers={"Authorization": "Bearer reader"})
    assert response.status_code == 200
    assert [item["snapshot_id"] for item in response.json()["snapshots"]] == ["snap-12345678"]

    monkeypatch.setattr(main.aws_service, "get_ec2_snapshots", lambda **kwargs: {
        "service": "ec2", "status": "healthy", "snapshots": [], "next_token": None, "is_truncated": False,
    })
    response = client.get("/cloud/aws/ec2/snapshots", headers={"Authorization": "Bearer reader"})
    assert response.status_code == 200 and response.json()["snapshots"] == []


def test_console_exposes_snapshot_pagination_and_export():
    html = TestClient(main.app).get("/console").text
    assert "Inspect EBS snapshots" in html
    assert "/cloud/aws/ec2/snapshots?" in html
    assert "Download snapshot CSV" in html
