from fastapi.testclient import TestClient

from main import app


def test_governance_api_exposes_read_only_report_contract():
    client = TestClient(app)

    response = client.get(
        "/autonomy/resources/ec2/i-task45-final/governance"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["provider"] == "aws"
    assert body["resource_type"] == "ec2"
    assert body["resource_id"] == "i-task45-final"
    assert body["read_only"] is True
    assert body["decision"] == "allow"
    assert body["allowed_for_decision"] is True
    assert body["blocked"] is False
    assert body["requires_human_review"] is False

    evidence = body["evidence"]
    assert evidence["decision"] == body["decision"]
    assert evidence["allowed"] is body["allowed_for_decision"]
    assert evidence["blocked"] is body["blocked"]
