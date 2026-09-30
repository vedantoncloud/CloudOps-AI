from dataclasses import replace

from autonomy.resource_policy import ResourcePolicy


def normalize_policy(policy: ResourcePolicy) -> ResourcePolicy:
    return replace(
        policy,
        allowed_providers={
            str(value).strip().lower()
            for value in policy.allowed_providers
            if str(value).strip()
        },
        allowed_resource_types={
            str(value).strip().lower()
            for value in policy.allowed_resource_types
            if str(value).strip()
        },
        required_metadata={
            str(value).strip()
            for value in policy.required_metadata
            if str(value).strip()
        },
        denied_tag_values={
            str(key).strip(): {
                str(value).strip()
                for value in values
            }
            for key, values in policy.denied_tag_values.items()
        },
    )
