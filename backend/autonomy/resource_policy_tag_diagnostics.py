from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_observer import ResourceObservation


def denied_tags(
    policy: ResourcePolicy,
    observation: ResourceObservation,
) -> dict[str, str]:
    tags = observation.data.get("tags", {})
    if not isinstance(tags, dict):
        return {}

    result: dict[str, str] = {}

    for key, denied_values in policy.denied_tag_values.items():
        if key not in tags:
            continue

        value = str(tags[key])

        if value in {str(item) for item in denied_values}:
            result[str(key)] = value

    return dict(sorted(result.items()))
