from datetime import datetime
from unittest.mock import patch

from botocore.exceptions import ClientError

from services.aws_service import AWSService


def _object(key, size):
    return {"Key": key, "Size": size, "LastModified": datetime(2026, 1, 1)}


def test_largest_object_scan_reports_when_limit_truncates_results():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.list_objects_v2.return_value = {
            "Contents": [_object("a", 1), _object("b", 2)],
            "IsTruncated": True,
            "NextContinuationToken": "more",
        }

        result = AWSService().get_s3_largest_objects("bucket", max_keys=2)

    assert result["status"] == "healthy"
    assert result["total_objects"] == 2
    assert result["scan_complete"] is False
    assert result["scan_limit"] == 2


def test_statistics_scan_reports_complete_when_last_page_is_within_limit():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.list_objects_v2.return_value = {
            "Contents": [_object("a", 1)],
            "IsTruncated": False,
        }

        result = AWSService().get_s3_object_statistics("bucket", max_keys=2)

    assert result == {
        "service": "s3",
        "status": "healthy",
        "bucket": "bucket",
        "prefix": None,
        "total_objects": 1,
        "total_size_bytes": 1,
        "scan_complete": True,
        "scan_limit": 2,
    }


def test_bucket_insights_propagate_scan_coverage_metadata():
    with patch.object(AWSService, "get_s3_largest_objects", return_value={
        "status": "healthy",
        "total_objects": 2,
        "total_size_bytes": 3,
        "average_object_size_bytes": 1.5,
        "largest_object": {"key": "b", "size": 2},
        "scan_complete": False,
        "scan_limit": 2,
    }):
        result = AWSService().get_s3_bucket_insights("bucket", max_keys=2)

    assert result["scan_complete"] is False
    assert result["scan_limit"] == 2


def test_object_scan_failure_remains_unhealthy_without_coverage_claim():
    with patch("services.aws_service.boto3.client") as client:
        client.return_value.list_objects_v2.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "ListObjectsV2",
        )

        result = AWSService().get_s3_largest_objects("bucket", max_keys=10)

    assert result["status"] == "unhealthy"
    assert "scan_complete" not in result
