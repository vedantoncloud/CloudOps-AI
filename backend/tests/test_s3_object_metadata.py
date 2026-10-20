from datetime import datetime, timezone
from unittest.mock import patch

from services.aws_service import AWSService


def test_s3_object_metadata_uses_head_object_and_returns_inspection_fields():
    modified = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.head_object.return_value = {
            "ContentLength": 42,
            "ContentType": "text/csv",
            "ETag": '"abc"',
            "LastModified": modified,
            "StorageClass": "STANDARD_IA",
            "ServerSideEncryption": "AES256",
            "Metadata": {"source": "billing"},
        }

        result = AWSService().get_s3_object_metadata("reports", "2026/month 1.csv")

    client.return_value.head_object.assert_called_once_with(
        Bucket="reports", Key="2026/month 1.csv"
    )
    assert result == {
        "service": "s3",
        "status": "healthy",
        "bucket": "reports",
        "object": {
            "key": "2026/month 1.csv",
            "version_id": None,
            "size": 42,
            "content_type": "text/csv",
            "etag": '"abc"',
            "last_modified": modified.isoformat(),
            "storage_class": "STANDARD_IA",
            "server_side_encryption": "AES256",
            "user_metadata": {"source": "billing"},
        },
    }


def test_s3_object_metadata_inspects_requested_version():
    modified = datetime(2026, 2, 3, tzinfo=timezone.utc)
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.head_object.return_value = {
            "VersionId": "version/1",
            "ContentLength": 9,
            "LastModified": modified,
            "Metadata": {"release": "old"},
        }

        result = AWSService().get_s3_object_metadata("reports", "archive.csv", "version/1")

    client.return_value.head_object.assert_called_once_with(
        Bucket="reports", Key="archive.csv", VersionId="version/1"
    )
    assert result["object"]["version_id"] == "version/1"
    assert result["object"]["user_metadata"] == {"release": "old"}


def test_s3_object_metadata_reports_missing_version_as_unhealthy():
    from botocore.exceptions import ClientError

    error = ClientError({"Error": {"Code": "NoSuchVersion", "Message": "missing"}}, "HeadObject")
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.head_object.side_effect = error

        result = AWSService().get_s3_object_metadata("reports", "archive.csv", "gone")

    assert result["status"] == "unhealthy"
    assert "NoSuchVersion" in result["error"]


def test_s3_download_url_is_a_short_lived_attachment_url():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.generate_presigned_url.return_value = "https://signed.example/object"

        result = AWSService().create_s3_object_download_url(
            "reports", "2026/month 1.csv"
        )

    client.return_value.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": "reports",
            "Key": "2026/month 1.csv",
            "ResponseContentDisposition": "attachment",
        },
        ExpiresIn=300,
    )
    assert result == {
        "service": "s3",
        "status": "healthy",
        "bucket": "reports",
        "key": "2026/month 1.csv",
        "url": "https://signed.example/object",
        "expires_in": 300,
    }
