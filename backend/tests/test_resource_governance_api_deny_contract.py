from fastapi.testclient import TestClient

from main import app


def test_governance_api_denies_unsupported_resource_type():
    client = TestClient(app)

    response = client.get(
        "/autonomy/resources/rds/db-task29-deny/governance"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["provider"] == "aws"
    assert body["resource_type"] == "rds"
    assert body["resource_id"] == "db-task29-deny"

    assert body["decision"] == "deny"
    assert body["blocked"] is True
    assert body["allowed_for_decision"] is False
    assert body["requires_human_review"] is False
    assert body["read_only"] is True

    evidence = body["evidence"]

    assert evidence["decision"] == "deny"
    assert evidence["allowed"] is False
    assert evidence["blocked"] is True
    assert evidence["requires_review"] is False
    assert evidence["reason_count"] == len(evidence["reasons"])
    assert evidence["reason_count"] > 0

    assert evidence["policy_evidence"]["resource_type_allowed"] is False
