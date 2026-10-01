from autonomy.resource_governance_serialization import serialize_governance_report


def test_serialization_returns_independent_nested_structure():
    report = {
        "decision": "allow",
        "evidence": {
            "reason_codes": ["provider_not_allowed"],
            "metadata": {"owner": "platform"},
        },
    }

    serialized = serialize_governance_report(report)

    serialized["evidence"]["reason_codes"].append("extra")
    serialized["evidence"]["metadata"]["owner"] = "changed"

    assert report["evidence"]["reason_codes"] == [
        "provider_not_allowed"
    ]
    assert report["evidence"]["metadata"]["owner"] == "platform"


def test_serialization_converts_non_json_values_to_strings():
    report = {
        "decision": "allow",
        "custom_value": object(),
    }

    serialized = serialize_governance_report(report)

    assert isinstance(serialized["custom_value"], str)
