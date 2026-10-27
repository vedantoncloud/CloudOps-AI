import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize(
    "path,method_name,kwargs",
    [
        ("", "get_s3_bucket_details", {}),
        ("/objects", "get_s3_objects", {"max_keys": 3}),
        ("/objects/metadata?key=logs%2Ftoday.json", "get_s3_object_metadata", {}),
        ("/object-versions", "get_s3_object_versions", {"max_keys": 3}),
        ("/objects/download?key=logs%2Ftoday.json", "create_s3_object_download_url", {}),
        ("/security-insights", "get_s3_security_insights", {}),
        ("/lifecycle", "get_s3_bucket_lifecycle", {}),
        ("/cost-insights", "get_s3_cost_insights", {}),
    ],
)
def test_s3_resource_endpoints_sanitize_provider_exceptions(
    monkeypatch, path, method_name, kwargs
):
    def fail(*args, **call_kwargs):
        raise RuntimeError("private AWS endpoint and credentials")

    monkeypatch.setattr(main.aws_service, method_name, fail)
    response = TestClient(main.app).get(f"/cloud/aws/s3/buckets/example{path}")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "credentials" not in response.text


def test_s3_object_listing_preserves_success_and_validation(monkeypatch):
    expected = {
        "service": "s3",
        "status": "healthy",
        "bucket": "example",
        "prefix": None,
        "objects": [{"key": "a.txt", "size": 1, "last_modified": None}],
        "common_prefixes": [],
        "is_truncated": False,
        "next_continuation_token": None,
    }
    monkeypatch.setattr(main.aws_service, "get_s3_objects", lambda *a, **k: expected)
    client = TestClient(main.app)

    success = client.get("/cloud/aws/s3/buckets/example/objects?max_keys=10")
    invalid = client.get("/cloud/aws/s3/buckets/example/objects?max_keys=1001")

    assert success.status_code == 200
    assert success.json() == expected
    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "max_keys must be between 1 and 1000"}


def test_s3_object_listing_preserves_valid_next_page_cursor(monkeypatch):
    expected = {
        "service": "s3",
        "status": "healthy",
        "bucket": "example",
        "prefix": "reports/",
        "objects": [{"key": "reports/a.csv", "size": 12, "last_modified": None}],
        "common_prefixes": ["reports/2026/"],
        "is_truncated": True,
        "next_continuation_token": "page-2",
    }
    monkeypatch.setattr(main.aws_service, "get_s3_objects", lambda *a, **k: expected)

    response = TestClient(main.app).get(
        "/cloud/aws/s3/buckets/example/objects?prefix=reports/"
    )

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize(
    "response",
    [
        {"service": "s3", "status": "healthy", "bucket": "other", "prefix": None,
         "objects": [], "common_prefixes": [], "is_truncated": False,
         "next_continuation_token": None},
        {"service": "s3", "status": "healthy", "bucket": "example", "prefix": None,
         "objects": [None], "common_prefixes": [], "is_truncated": False,
         "next_continuation_token": None},
        {"service": "s3", "status": "healthy", "bucket": "example", "prefix": None,
         "objects": [{"key": "a", "size": True, "last_modified": None}],
         "common_prefixes": [], "is_truncated": False, "next_continuation_token": None},
        {"service": "s3", "status": "healthy", "bucket": "example", "prefix": None,
         "objects": [], "common_prefixes": [], "is_truncated": True,
         "next_continuation_token": None},
    ],
)
def test_s3_object_listing_rejects_malformed_provider_contract(monkeypatch, response):
    monkeypatch.setattr(main.aws_service, "get_s3_objects", lambda *a, **k: response)

    result = TestClient(main.app).get("/cloud/aws/s3/buckets/example/objects")

    assert result.status_code == 503
    assert result.json() == {"detail": "AWS resource data is unavailable"}


def test_s3_resource_endpoint_rejects_malformed_provider_response(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_s3_bucket_details", lambda *_: None)

    response = TestClient(main.app).get("/cloud/aws/s3/buckets/example")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
