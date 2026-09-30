from autonomy.resource_policy_reasons import ResourcePolicyReason


def test_resource_policy_reason_codes_are_stable():
    assert ResourcePolicyReason.PROVIDER_NOT_ALLOWED.value == "provider_not_allowed"
    assert ResourcePolicyReason.RESOURCE_TYPE_NOT_ALLOWED.value == "resource_type_not_allowed"
    assert ResourcePolicyReason.READ_ONLY_REQUIRED.value == "read_only_required"
    assert ResourcePolicyReason.REQUIRED_METADATA_MISSING.value == "required_metadata_missing"
    assert ResourcePolicyReason.DENIED_TAG.value == "denied_tag"
