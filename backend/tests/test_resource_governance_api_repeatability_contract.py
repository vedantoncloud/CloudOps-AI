from fastapi.testclient import TestClient

from main import app


def test_governance_api_repeated_allow_response_is_identical():
    client = TestClient(app)

    path = "/autonomy/resources/ec2/i-task30-repeat/governance"

    first = client.get(path)
    second = client.get(path)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_governance_api_repeated_deny_response_is_identical():
    client = TestClient(app)

    path = "/autonomy/resources/rds/db-task30-repeat/governance"

    first = client.get(path)
    second = client.get(path)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_governance_api_top_level_and_evidence_decisions_match():
    client = TestClient(app)

    response = client.get(
        "/autonomy/resources/rds/db-task30-evidence/governance"
    )

    assert response.status_code == 200

    body = response.json()
    evidence = body["evidence"]

    assert body["decision"] == evidence["decision"]
    assert body["allowed_for_decision"] == evidence["allowed"]
    assert body["blocked"] == evidence["blocked"]
    assert (
        body["requires_human_review"]
        == evidence["requires_review"]
    )
    assert body["read_only"] is True
    assert evidence["reason_count"] == len(evidence["reasons"])
