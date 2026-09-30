
from autonomy.resource_governance_serialization import (
    serialize_governance_report,
)


def test_governance_report_serialization_is_deterministic():
    report = {
        "resource_id": "i-serialization-123",
        "resource_type": "ec2",
        "provider": "aws",
        "decision": "allow",
        "allowed_for_decision": True,
        "blocked": False,
        "requires_human_review": False,
        "read_only": True,
        "evidence": {
            "decision": "allow",
            "allowed": True,
        },
    }

    first = serialize_governance_report(report)
    second = serialize_governance_report(report)

    assert first == second
