from datetime import datetime, timezone
from unittest.mock import patch

import pytest
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


def test_s3_version_download_signs_exact_version_as_attachment():
    with patch("services.aws_service._aws_client") as client:
        client.return_value.generate_presigned_url.return_value = "https://signed.example/version"
        result = AWSService().create_s3_object_download_url(
            "owned", "reports/a.csv", "version / one"
        )

    client.return_value.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": "owned", "Key": "reports/a.csv", "VersionId": "version / one",
            "ResponseContentDisposition": "attachment",
        },
        ExpiresIn=300,
    )
    assert result["status"] == "healthy"
    assert result["url"] == "https://signed.example/version"


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

    def get_s3_object_metadata(self, bucket_name, key, version_id=None):
        if self.unavailable:
            return {"service": "s3", "status": "unhealthy", "error": "account diagnostic"}
        return {"service": "s3", "status": "healthy", "bucket": bucket_name,
                "object": {"key": key, "version_id": version_id, "size": 9,
                           "user_metadata": {"release": "old"}}}

    def create_s3_object_download_url(self, bucket_name, key, version_id=None):
        if self.unavailable:
            return {"status": "unhealthy", "error": "account diagnostic"}
        return {
            "service": "s3", "status": "healthy", "bucket": bucket_name,
            "key": key, "url": "https://signed.example/object",
            "expires_in": 300, "version_id": version_id,
        }


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


@pytest.mark.parametrize("payload", [
    {"service": "s3", "status": "healthy", "bucket": "other",
     "versions": [], "is_truncated": False},
    {"service": "s3", "status": "healthy", "bucket": "owned",
     "versions": {}, "is_truncated": False},
    {"service": "s3", "status": "healthy", "bucket": "owned",
     "versions": [{"key": "a", "version_id": "v1", "is_latest": 1,
                   "delete_marker": False}], "is_truncated": False},
    {"service": "s3", "status": "healthy", "bucket": "owned",
     "versions": [{"key": "a", "version_id": "v1", "is_latest": False,
                   "delete_marker": False, "size": True}], "is_truncated": False},
    {"service": "s3", "status": "healthy", "bucket": "owned",
     "versions": [], "is_truncated": True},
])
def test_s3_versions_endpoint_rejects_malformed_healthy_payloads(monkeypatch, payload):
    monkeypatch.setattr(
        main.aws_service, "get_s3_object_versions", lambda *_args, **_kwargs: payload
    )

    response = TestClient(main.app).get("/cloud/aws/s3/buckets/owned/object-versions")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_s3_version_download_is_tenant_scoped_and_preserves_version_id(monkeypatch):
    client = version_client(monkeypatch)
    response = client.get(
        "/cloud/aws/s3/buckets/owned/objects/download?key=reports%2Fa.csv&version_id=v%2F2",
        headers={"Authorization": "Bearer a"},
    )
    assert response.status_code == 200
    assert response.json()["version_id"] == "v/2"

    foreign = client.get(
        "/cloud/aws/s3/buckets/foreign/objects/download?key=reports%2Fa.csv&version_id=v2",
        headers={"Authorization": "Bearer a"},
    )
    assert foreign.status_code == 404


def test_s3_version_download_sanitizes_provider_failure(monkeypatch):
    client = version_client(monkeypatch)
    main.aws_service.unavailable = True
    response = client.get(
        "/cloud/aws/s3/buckets/owned/objects/download?key=reports%2Fa.csv&version_id=v2",
        headers={"Authorization": "Bearer a"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_s3_version_download_rejects_empty_version_id_before_provider_call(monkeypatch):
    client = version_client(monkeypatch)
    response = client.get(
        "/cloud/aws/s3/buckets/owned/objects/download?key=reports%2Fa.csv&version_id=",
        headers={"Authorization": "Bearer a"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "version_id must not be empty"}


@pytest.mark.parametrize("payload", [
    {"service": "s3", "status": "healthy", "bucket": "other", "key": "file",
     "url": "https://signed.example/object", "expires_in": 300},
    {"service": "s3", "status": "healthy", "bucket": "owned", "key": "other",
     "url": "https://signed.example/object", "expires_in": 300},
    {"service": "s3", "status": "healthy", "bucket": "owned", "key": "file",
     "url": "javascript:alert(1)", "expires_in": 300},
    {"service": "s3", "status": "healthy", "bucket": "owned", "key": "file",
     "url": "https://user:secret@signed.example/object", "expires_in": 300},
    {"service": "s3", "status": "healthy", "bucket": "owned", "key": "file",
     "url": "https://signed.example/object", "expires_in": 3600},
    {"service": "s3", "status": "healthy", "bucket": "owned", "key": "file",
     "url": "https://signed.example/object", "expires_in": 300, "version_id": "other"},
])
def test_s3_download_rejects_malformed_healthy_payloads(monkeypatch, payload):
    monkeypatch.setattr(main.aws_service, "create_s3_object_download_url", lambda *_a, **_k: payload)

    response = TestClient(main.app).get(
        "/cloud/aws/s3/buckets/owned/objects/download?key=file&version_id=v1"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_s3_version_metadata_is_tenant_scoped_and_preserves_encoded_identifiers(monkeypatch):
    client = version_client(monkeypatch)
    response = client.get(
        "/cloud/aws/s3/buckets/owned/objects/metadata?key=archive%2Freport.csv&version_id=v%2F2",
        headers={"Authorization": "Bearer a"},
    )
    assert response.status_code == 200
    assert response.json()["object"] == {
        "key": "archive/report.csv", "version_id": "v/2", "size": 9,
        "user_metadata": {"release": "old"},
    }

    foreign = client.get(
        "/cloud/aws/s3/buckets/foreign/objects/metadata?key=archive.csv&version_id=v2",
        headers={"Authorization": "Bearer a"},
    )
    assert foreign.status_code == 404


def test_s3_version_metadata_sanitizes_provider_failure_and_rejects_empty_version(monkeypatch):
    client = version_client(monkeypatch)
    headers = {"Authorization": "Bearer a"}
    main.aws_service.unavailable = True
    failed = client.get(
        "/cloud/aws/s3/buckets/owned/objects/metadata?key=archive.csv&version_id=v2",
        headers=headers,
    )
    assert failed.status_code == 503
    assert failed.json() == {"detail": "AWS resource data is unavailable"}

    malformed = client.get(
        "/cloud/aws/s3/buckets/owned/objects/metadata?key=archive.csv&version_id=",
        headers=headers,
    )
    assert malformed.status_code == 400
    assert malformed.json() == {"detail": "version_id must not be empty"}


def test_console_exposes_version_browsing_pagination_and_download():
    html = main.CONSOLE_PAGE.read_text(encoding="utf-8")
    assert 'id="objectVersions"' in html
    assert 'id="moreVersions"' in html
    assert "object-versions?${query}" in html
    assert "query.set('version_id',versionId)" in html
    assert "Download version" in html
    assert "Object version metadata" in html
    assert "No user metadata reported." in html
    assert "description.textContent=String(value)" in html
