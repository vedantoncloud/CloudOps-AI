from autonomy.resource_governance_evidence import build_governance_evidence
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyDecision, ResourcePolicyResult


def test_governance_evidence_contains_policy_and_decision():
    policy = ResourcePolicy()

    result = ResourcePolicyResult(
        decision=ResourcePolicyDecision.ALLOW,
        reasons=["ok"],
        evidence={"read_only": True},
    )

    evidence = build_governance_evidence(policy, result)

    assert evidence["decision"] == "allow"
    assert evidence["allowed"] is True
    assert evidence["policy"]["allowed_providers"] == ["aws"]
    assert evidence["policy_evidence"]["read_only"] is True


def test_evidence_contains_deterministic_policy_snapshot():
    from autonomy.resource_governance_evidence import build_governance_evidence
    from autonomy.resource_policy import ResourcePolicy, ResourcePolicyResult
    from autonomy.resource_policy import ResourcePolicyDecision

    policy = ResourcePolicy(
        allowed_providers={"AWS"},
        allowed_resource_types={"EC2"},
        required_metadata={"environment"},
    )

    result = ResourcePolicyResult(
        decision=ResourcePolicyDecision.ALLOW,
        reasons=["ok"],
        evidence={},
    )

    evidence = build_governance_evidence(policy, result)

    assert evidence["policy"]["allowed_providers"] == ["aws"]
    assert evidence["policy"]["allowed_resource_types"] == ["ec2"]


def test_reason_codes_are_stable():
    from autonomy.resource_governance_evidence import reason_codes

    reasons = [
        "Resource contains a denied tag value.",
        "Provider 'x' is not allowed by resource policy.",
        "Required resource metadata is missing: environment",
    ]

    assert reason_codes(reasons) == [
        "denied_tag",
        "provider_not_allowed",
        "required_metadata_missing",
    ]
