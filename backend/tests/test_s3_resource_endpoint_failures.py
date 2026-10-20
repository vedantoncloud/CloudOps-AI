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
    expected = {"status": "healthy", "objects": [{"key": "a.txt"}], "is_truncated": False}
    monkeypatch.setattr(main.aws_service, "get_s3_objects", lambda *a, **k: expected)
    client = TestClient(main.app)

    success = client.get("/cloud/aws/s3/buckets/example/objects?max_keys=10")
    invalid = client.get("/cloud/aws/s3/buckets/example/objects?max_keys=1001")

    assert success.status_code == 200
    assert success.json() == expected
    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "max_keys must be between 1 and 1000"}


def test_s3_resource_endpoint_rejects_malformed_provider_response(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_s3_bucket_details", lambda *_: None)

    response = TestClient(main.app).get("/cloud/aws/s3/buckets/example")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
