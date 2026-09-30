from fastapi.testclient import TestClient

from main import app


def test_governance_api_end_to_end_contract():
    client = TestClient(app)

    response = client.get(
        "/autonomy/resources/ec2/i-task24-e2e/governance"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["provider"] == "aws"
    assert body["resource_type"] == "ec2"
    assert body["resource_id"] == "i-task24-e2e"

    assert body["read_only"] is True

    assert body["decision"] == "allow"
    assert body["allowed_for_decision"] is True
    assert body["blocked"] is False
    assert body["requires_human_review"] is False

    assert "evidence" in body

    evidence = body["evidence"]

    assert evidence["allowed"] is True
    assert evidence["blocked"] is False
    assert evidence["decision"] == "allow"
    assert evidence["requires_review"] is False

    assert "policy" in evidence
    assert "policy_evidence" in evidence
    assert "reason_count" in evidence
    assert "reasons" in evidence

    assert evidence["reason_count"] == len(evidence["reasons"])
    assert evidence["reason_count"] >= 1
