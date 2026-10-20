import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize(
    "path,method_name",
    [
        ("statistics", "get_s3_object_statistics"),
        ("largest-objects", "get_s3_largest_objects"),
        ("health", "get_s3_bucket_health"),
        ("insights", "get_s3_bucket_insights"),
        ("optimization", "get_s3_bucket_optimization"),
    ],
)
def test_s3_analysis_provider_exceptions_are_sanitized(monkeypatch, path, method_name):
    def fail(*args, **kwargs):
        raise RuntimeError("private AWS endpoint and credentials")

    monkeypatch.setattr(main.aws_service, method_name, fail)
    response = TestClient(main.app).get(f"/cloud/aws/s3/buckets/example/{path}")
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "credentials" not in response.text


def test_s3_analysis_preserves_success_and_rejects_invalid_limits(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_s3_bucket_health",
        lambda *args, **kwargs: {"status": "healthy", "object_count": 2},
    )
    client = TestClient(main.app)
    success = client.get("/cloud/aws/s3/buckets/example/health?max_keys=10")
    invalid = client.get("/cloud/aws/s3/buckets/example/health?max_keys=1001")
    assert success.status_code == 200
    assert success.json() == {"status": "healthy", "object_count": 2}
    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "max_keys must be between 1 and 1000"}


def test_s3_analysis_maps_unhealthy_results_to_dependency_error(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_s3_bucket_insights",
        lambda *args, **kwargs: {"status": "unhealthy", "error": "internal detail"},
    )
    response = TestClient(main.app).get("/cloud/aws/s3/buckets/example/insights")
    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
