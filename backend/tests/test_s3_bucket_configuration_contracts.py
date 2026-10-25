import pytest
from fastapi.testclient import TestClient

import main


VALID = {
    "details": {"service": "s3", "status": "healthy", "bucket": "archive", "region": "us-east-1"},
    "versioning": {"service": "s3", "status": "healthy", "bucket": "archive", "versioning": "disabled", "mfa_delete": "disabled"},
    "lifecycle": {"service": "s3", "status": "healthy", "bucket": "archive", "configured": False, "rule_count": 0, "enabled_rule_count": 0, "rules": []},
    "replication": {"service": "s3", "status": "healthy", "bucket": "archive", "configured": False, "rule_count": 0, "enabled_rule_count": 0, "rules": []},
    "logging": {"service": "s3", "status": "healthy", "bucket": "archive", "configured": False, "destination_bucket": None, "destination_prefix": "", "target_grants": []},
    "encryption": {"service": "s3", "status": "healthy", "bucket": "archive", "configured": False, "rule_count": 0, "rules": []},
    "tags": {"status": "healthy", "bucket": "archive", "tags": {}},
    "policy": {"service": "s3", "status": "healthy", "bucket": "archive", "configured": False, "policy": None},
}

ROUTES = {
    "details": ("", "get_s3_bucket_details"),
    "versioning": ("/versioning", "get_s3_bucket_versioning"),
    "lifecycle": ("/lifecycle", "get_s3_bucket_lifecycle"),
    "replication": ("/replication", "get_s3_bucket_replication"),
    "logging": ("/logging", "get_s3_bucket_logging"),
    "encryption": ("/encryption", "get_s3_bucket_encryption"),
    "tags": ("/tags", "get_s3_bucket_tags"),
    "policy": ("/policy", "get_s3_bucket_policy"),
}


@pytest.mark.parametrize("kind", list(ROUTES))
def test_s3_bucket_configuration_contract_preserves_valid_empty_state(monkeypatch, kind):
    path, method = ROUTES[kind]
    monkeypatch.setattr(main.aws_service, method, lambda *_: VALID[kind])

    response = TestClient(main.app).get(f"/cloud/aws/s3/buckets/archive{path}")

    assert response.status_code == 200
    assert response.json() == VALID[kind]


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("details", {**VALID["details"], "bucket": "other"}),
        ("details", {**VALID["details"], "region": "  "}),
        ("versioning", {**VALID["versioning"], "versioning": "unknown"}),
        ("versioning", {**VALID["versioning"], "versioning": []}),
        ("versioning", {**VALID["versioning"], "mfa_delete": "yes"}),
        ("lifecycle", {**VALID["lifecycle"], "rule_count": 1}),
        ("lifecycle", {**VALID["lifecycle"], "rules": [None]}),
        ("replication", {**VALID["replication"], "enabled_rule_count": True}),
        ("logging", {**VALID["logging"], "target_grants": {}}),
        ("logging", {**VALID["logging"], "configured": True}),
        ("encryption", {**VALID["encryption"], "configured": True}),
        ("encryption", {**VALID["encryption"], "rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": " "}}]}),
        ("tags", {**VALID["tags"], "tags": {"owner": None}}),
        ("policy", {**VALID["policy"], "configured": True}),
        ("policy", {**VALID["policy"], "policy": []}),
    ],
)
def test_s3_bucket_configuration_contract_rejects_malformed_healthy_response(
    monkeypatch, kind, payload
):
    path, method = ROUTES[kind]
    monkeypatch.setattr(main.aws_service, method, lambda *_: payload)

    response = TestClient(main.app).get(f"/cloud/aws/s3/buckets/archive{path}")

    assert response.status_code == 503
    assert response.json() == {"detail": "AWS resource data is unavailable"}


def test_s3_bucket_configuration_contract_rejects_wrong_bucket_and_provider_failure(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_s3_bucket_policy", lambda *_: {
        **VALID["policy"], "bucket": "another-bucket",
    })
    client = TestClient(main.app)
    malformed = client.get("/cloud/aws/s3/buckets/archive/policy")
    monkeypatch.setattr(
        main.aws_service, "get_s3_bucket_policy",
        lambda *_: {"service": "s3", "status": "unhealthy", "error": "private endpoint"},
    )
    unavailable = client.get("/cloud/aws/s3/buckets/archive/policy")

    assert malformed.status_code == unavailable.status_code == 503
    assert malformed.json() == unavailable.json() == {"detail": "AWS resource data is unavailable"}
    assert "private endpoint" not in unavailable.text
