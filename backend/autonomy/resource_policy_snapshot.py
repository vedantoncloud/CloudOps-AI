from autonomy.resource_policy import ResourcePolicy


def policy_snapshot(policy: ResourcePolicy) -> dict:
    return {
        "allowed_providers": sorted(
            str(value).strip().lower()
            for value in policy.allowed_providers
        ),
        "allowed_resource_types": sorted(
            str(value).strip().lower()
            for value in policy.allowed_resource_types
        ),
        "require_read_only": bool(policy.require_read_only),
        "required_metadata": sorted(
            str(value).strip()
            for value in policy.required_metadata
        ),
        "denied_tag_values": {
            str(key).strip(): sorted(str(value) for value in values)
            for key, values in sorted(
                policy.denied_tag_values.items()
            )
        },
    }
