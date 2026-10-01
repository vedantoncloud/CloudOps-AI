from copy import deepcopy

from autonomy.resource_governance_serialization import (
    serialize_governance_report,
)


def test_governance_serialization_does_not_mutate_input():
    report = {
        "decision": "allow",
        "evidence": {
            "reasons": ["Resource satisfies policy."],
            "reason_codes": [],
        },
    }
    original = deepcopy(report)

    serialized = serialize_governance_report(report)

    assert serialized == original
    assert report == original
    assert serialized is not report
    assert serialized["evidence"] is not report["evidence"]
