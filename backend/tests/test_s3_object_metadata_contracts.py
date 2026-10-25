import pytest
from fastapi.testclient import TestClient

import main


VALID = {
    "service": "s3",
    "status": "healthy",
    "bucket": "archive",
    "object": {
        "key": "reports/month 1.csv",
        "version_id": "v1",
        "size": 0,
        "content_type": "text/csv",
        "etag": '"abc"',
        "last_modified": "2026-10-25T00:00:00+00:00",
        "storage_class": "STANDARD",
        "server_side_encryption": None,
        "user_metadata": {},
    },
}


def _get(monkeypatch, payload, query="key=reports%2Fmonth%201.csv&version_id=v1"):
    monkeypatch.setattr(main.aws_service, "get_s3_object_metadata", lambda *_: payload)
    return TestClient(main.app).get(
        f"/cloud/aws/s3/buckets/archive/objects/metadata?{query}"
    )


def test_s3_object_metadata_contract_preserves_valid_empty_optional_fields(monkeypatch):
    payload = {
        **VALID,
        "object": {
            **VALID["object"],
            "content_type": None,
            "etag": None,
            "last_modified": None,
            "user_metadata": {},
        },
    }

    response = _get(monkeypatch, payload)

    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.parametrize(
    "change",
    [
        {"bucket": "other"},
        {"service": "ec2"},
        {"object": {"key": "other.csv"}},
        {"object": {"version_id": "other-version"}},
        {"object": {"size": -1}},
        {"object": {"size": True}},
        {"object": {"size": "12"}},
        {"object": {"etag": []}},
        {"object": {"user_metadata": []}},
        {"object": {"user_metadata": {"owner": None}}},
    ],
)
def test_s3_object_metadata_contract_rejects_malformed_healthy_response(
    monkeypatch, change
):
    payload = {**VALID, **change}
    if "object" in change:
        payload["object"] = {**VALID["object"], **change["object"]}

    response = _get(monkeypatch, payload)

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_s3_object_metadata_contract_sanitizes_provider_failure(monkeypatch):
    def fail(*_args):
        raise RuntimeError("private endpoint and credentials")

    monkeypatch.setattr(main.aws_service, "get_s3_object_metadata", fail)
    response = TestClient(main.app).get(
        "/cloud/aws/s3/buckets/archive/objects/metadata?key=report.csv"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}
    assert "credentials" not in response.text


@pytest.mark.parametrize("query", ["key=", "key=report.csv&version_id="])
def test_s3_object_metadata_rejects_empty_identifiers_before_provider_call(
    monkeypatch, query
):
    def unexpected(*_args):
        pytest.fail("provider must not be called for an empty object identifier")

    monkeypatch.setattr(main.aws_service, "get_s3_object_metadata", unexpected)
    response = TestClient(main.app).get(
        f"/cloud/aws/s3/buckets/archive/objects/metadata?{query}"
    )

    assert response.status_code == 400
