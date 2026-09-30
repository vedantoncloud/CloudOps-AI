

def test_governance_report_serialization_is_json_safe_and_deterministic():
    from autonomy.resource_governance_serialization import (
        serialize_governance_report,
    )

    report = {
        "decision": "allow",
        "allowed": True,
        "evidence": {
            "reason_codes": ["provider_not_allowed"],
        },
    }

    first = serialize_governance_report(report)
    second = serialize_governance_report(report)

    assert first == second
    assert first["decision"] == "allow"
    assert first["evidence"]["reason_codes"] == ["provider_not_allowed"]
