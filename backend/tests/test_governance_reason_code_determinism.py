from autonomy.resource_governance_evidence import reason_codes


def test_reason_codes_are_sorted_and_unique():
    reasons = [
        "Provider 'gcp' is not allowed by resource policy.",
        "Provider 'gcp' is not allowed by resource policy.",
        "Resource type 'rds' is not allowed by resource policy.",
    ]

    codes = reason_codes(reasons)

    assert codes == sorted(set(codes))
    assert "provider_not_allowed" in codes
    assert "resource_type_not_allowed" in codes
