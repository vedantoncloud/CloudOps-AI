from datetime import datetime, timezone
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from auth import AccessControlMiddleware, Principal
from services.aws_service import AWSService


def test_s3_object_versions_serializes_versions_and_delete_markers_and_paginates():
    modified = datetime(2026, 3, 4, tzinfo=timezone.utc)
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.list_object_versions.return_value = {
            "Versions": [{"Key": "reports/a.csv", "VersionId": "v2", "IsLatest": True,
                          "LastModified": modified, "Size": 18, "ETag": '"sum"',
                          "StorageClass": "STANDARD"}],
            "DeleteMarkers": [{"Key": "reports/gone.csv", "VersionId": "d1",
                               "IsLatest": True, "LastModified": modified}],
            "IsTruncated": True,
            "NextKeyMarker": "reports/z.csv",
            "NextVersionIdMarker": "v1",
        }

        result = AWSService().get_s3_object_versions(
            "owned", prefix="reports/", key_marker="reports/a.csv",
            version_id_marker="v1", max_keys=25,
        )

    client.return_value.list_object_versions.assert_called_once_with(
        Bucket="owned", Prefix="reports/", KeyMarker="reports/a.csv",
        VersionIdMarker="v1", MaxKeys=25,
    )
    assert result["status"] == "healthy"
    assert result["is_truncated"] is True
    assert result["next_key_marker"] == "reports/z.csv"
    assert result["next_version_id_marker"] == "v1"
    assert result["versions"] == [
        {"key": "reports/a.csv", "version_id": "v2", "is_latest": True,
         "last_modified": modified.isoformat(), "size": 18, "etag": '"sum"',
         "storage_class": "STANDARD", "delete_marker": False},
        {"key": "reports/gone.csv", "version_id": "d1", "is_latest": True,
         "last_modified": modified.isoformat(), "size": None, "etag": None,
         "storage_class": None, "delete_marker": True},
    ]


def test_s3_object_versions_reports_provider_failure_without_partial_page():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.list_object_versions.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "ListObjectVersions",
        )
        result = AWSService().get_s3_object_versions("owned")

    assert result["status"] == "unhealthy"
    assert "versions" not in result


class VersionAWS:
    unavailable = False

    def get_s3_bucket_tags(self, bucket_name):
        if bucket_name == "owned":
            return {"status": "healthy", "tags": {"CloudOpsTenantId": "tenant-a"}}
        return {"status": "healthy", "tags": {"CloudOpsTenantId": "tenant-b"}}

    def get_s3_object_versions(self, bucket_name, **kwargs):
        if self.unavailable:
            return {"service": "s3", "status": "unhealthy", "error": "account diagnostic"}
        return {"service": "s3", "status": "healthy", "bucket": bucket_name,
                "versions": [], "is_truncated": False}


def version_client(monkeypatch):
    monkeypatch.setattr(main, "aws_service", VersionAWS())
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "a": Principal("alice", "reader", "tenant-a"),
    })
    return TestClient(app)


def test_s3_versions_endpoint_scopes_bucket_and_rejects_invalid_page_size(monkeypatch):
    client = version_client(monkeypatch)
    headers = {"Authorization": "Bearer a"}
    assert client.get("/cloud/aws/s3/buckets/owned/object-versions?max_keys=25", headers=headers).status_code == 200
    assert client.get("/cloud/aws/s3/buckets/foreign/object-versions", headers=headers).status_code == 404
    assert client.get("/cloud/aws/s3/buckets/owned/object-versions?max_keys=1001", headers=headers).status_code == 400


def test_s3_versions_endpoint_sanitizes_provider_failure(monkeypatch):
    client = version_client(monkeypatch)
    main.aws_service.unavailable = True
    response = client.get(
        "/cloud/aws/s3/buckets/owned/object-versions",
        headers={"Authorization": "Bearer a"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
