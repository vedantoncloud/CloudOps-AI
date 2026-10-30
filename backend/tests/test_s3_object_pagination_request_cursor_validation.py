import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize(
    "path,params,method",
    [
        (
            "/cloud/aws/s3/buckets/owned/objects",
            {"continuation_token": ""},
            "get_s3_objects",
        ),
        (
            "/cloud/aws/s3/buckets/owned/objects",
            {"continuation_token": "   "},
            "get_s3_objects",
        ),
        (
            "/cloud/aws/s3/buckets/owned/objects",
            {"continuation_token": "x" * 4097},
            "get_s3_objects",
        ),
        (
            "/cloud/aws/s3/buckets/owned/object-versions",
            {"key_marker": ""},
            "get_s3_object_versions",
        ),
        (
            "/cloud/aws/s3/buckets/owned/object-versions",
            {"key_marker": "   "},
            "get_s3_object_versions",
        ),
        (
            "/cloud/aws/s3/buckets/owned/object-versions",
            {"key_marker": "x" * 4097},
            "get_s3_object_versions",
        ),
        (
            "/cloud/aws/s3/buckets/owned/object-versions",
            {"version_id_marker": ""},
            "get_s3_object_versions",
        ),
        (
            "/cloud/aws/s3/buckets/owned/object-versions",
            {"version_id_marker": "   "},
            "get_s3_object_versions",
        ),
        (
            "/cloud/aws/s3/buckets/owned/object-versions",
            {"version_id_marker": "x" * 4097},
            "get_s3_object_versions",
        ),
    ],
)
def test_s3_object_pagination_rejects_invalid_request_cursors_before_provider_call(
    monkeypatch, path, params, method
):
    monkeypatch.setattr(main, "_require_tenant_s3_bucket", lambda *_args: None)

    def unexpected_provider_call(*_args, **_kwargs):
        pytest.fail("invalid S3 pagination cursor must be rejected before AWS is called")

    monkeypatch.setattr(main.aws_service, method, unexpected_provider_call)

    response = TestClient(main.app).get(path, params=params)

    assert response.status_code == 400
    assert "must contain 1 to 4096 non-whitespace characters" in response.json()["detail"]


def test_s3_object_pagination_forwards_valid_request_cursors(monkeypatch):
    monkeypatch.setattr(main, "_require_tenant_s3_bucket", lambda *_args: None)
    calls = []

    def list_objects(bucket_name, **kwargs):
        calls.append((bucket_name, kwargs))
        return {
            "service": "s3",
            "status": "healthy",
            "bucket": bucket_name,
            "prefix": None,
            "objects": [],
            "common_prefixes": [],
            "is_truncated": False,
            "next_continuation_token": None,
        }

    def list_versions(bucket_name, **kwargs):
        calls.append((bucket_name, kwargs))
        return {
            "service": "s3",
            "status": "healthy",
            "bucket": bucket_name,
            "versions": [],
            "is_truncated": False,
        }

    monkeypatch.setattr(main.aws_service, "get_s3_objects", list_objects)
    monkeypatch.setattr(main.aws_service, "get_s3_object_versions", list_versions)

    client = TestClient(main.app)
    objects = client.get(
        "/cloud/aws/s3/buckets/owned/objects",
        params={"continuation_token": "cursor-1"},
    )
    versions = client.get(
        "/cloud/aws/s3/buckets/owned/object-versions",
        params={"key_marker": "reports/a.csv", "version_id_marker": "v/2"},
    )

    assert objects.status_code == 200
    assert versions.status_code == 200
    assert calls == [
        ("owned", {
            "prefix": None, "max_keys": 1000,
            "continuation_token": "cursor-1", "delimiter": None,
        }),
        ("owned", {
            "prefix": None, "key_marker": "reports/a.csv",
            "version_id_marker": "v/2", "max_keys": 100,
        }),
    ]
