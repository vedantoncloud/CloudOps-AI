from fastapi import FastAPI
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

import main
from auth import AccessControlMiddleware, Principal
from services.aws_service import AWSService


def volume(volume_id, tenant, attachments=None):
    return {
        "volume_id": volume_id, "state": "available" if not attachments else "in-use",
        "size_gib": 20, "volume_type": "gp3", "encrypted": True,
        "kms_key_id": "key-1", "availability_zone": "us-east-1a",
        "iops": 3000, "throughput": 125, "create_time": None,
        "tags": {"CloudOpsTenantId": tenant}, "attachments": attachments or [],
    }


def test_volume_inventory_maps_provider_metadata_and_page_cursor(monkeypatch):
    class Client:
        def describe_volumes(self, **kwargs):
            assert kwargs == {"MaxResults": 5, "NextToken": "cursor", "Filters": [{"Name": "status", "Values": ["available"]}]}
            return {"Volumes": [{
                "VolumeId": "vol-12345678", "State": "available", "Size": 20,
                "VolumeType": "gp3", "Encrypted": True, "KmsKeyId": "key-1",
                "AvailabilityZone": "us-east-1a", "Iops": 3000, "Throughput": 125,
                "Tags": [{"Key": "CloudOpsTenantId", "Value": "tenant-a"}],
                "Attachments": [],
            }], "NextToken": "next"}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Client())
    result = AWSService().get_ec2_volumes(max_results=5, next_token="cursor", region="us-east-1", unattached_only=True)
    assert result["status"] == "healthy"
    assert result["is_truncated"] is True
    assert result["next_token"] == "next"
    assert result["volumes"][0]["tags"] == {"CloudOpsTenantId": "tenant-a"}
    assert result["volumes"][0]["attachments"] == []


def test_volume_inventory_provider_failure_and_malformed_data_fail_closed(monkeypatch):
    class Broken:
        def describe_volumes(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret"}}, "DescribeVolumes")

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Broken())
    assert AWSService().get_ec2_volumes()["status"] == "unhealthy"

    class Malformed:
        def describe_volumes(self, **kwargs):
            return {"Volumes": [{"VolumeId": "vol-12345678", "Tags": "bad", "Attachments": []}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Malformed())
    assert AWSService().get_ec2_volumes()["status"] == "unhealthy"


def test_volume_endpoint_validates_input_and_provider_contract(monkeypatch):
    calls = []
    monkeypatch.setattr(main.aws_service, "get_ec2_volumes", lambda **kwargs: calls.append(kwargs) or {
        "service": "ec2", "status": "healthy", "volumes": [], "next_token": None, "is_truncated": False,
    })
    client = TestClient(main.app)
    assert client.get("/cloud/aws/ec2/volumes?region=bad").status_code == 400
    assert client.get("/cloud/aws/ec2/volumes?max_results=2").status_code == 400
    assert calls == []

    monkeypatch.setattr(main.aws_service, "get_ec2_volumes", lambda **kwargs: {
        "service": "ec2", "status": "healthy", "volumes": [volume("vol-12345678", "tenant-a")],
        "next_token": "next", "is_truncated": False,
    })
    response = client.get("/cloud/aws/ec2/volumes")
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_volume_endpoint_tenant_scope_auth_and_unattached_filter_data(monkeypatch):
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "reader": Principal("alice", "reader", "tenant-a"),
    })
    monkeypatch.setattr(main.aws_service, "get_ec2_volumes", lambda **kwargs: {
        "service": "ec2", "status": "healthy",
        "volumes": [volume("vol-12345678", "tenant-a"), volume("vol-87654321", "tenant-b")],
        "next_token": None, "is_truncated": False,
    })
    client = TestClient(app)
    assert client.get("/cloud/aws/ec2/volumes").status_code == 401
    response = client.get("/cloud/aws/ec2/volumes", headers={"Authorization": "Bearer reader"})
    assert response.status_code == 200
    assert [item["volume_id"] for item in response.json()["volumes"]] == ["vol-12345678"]


def test_console_exposes_paginated_unattached_volume_inventory():
    html = TestClient(main.app).get("/console").text
    assert "Inspect EBS volumes" in html
    assert "Show unattached volumes only" in html
    assert "Download volume CSV" in html
    assert "/cloud/aws/ec2/volumes?" in html
