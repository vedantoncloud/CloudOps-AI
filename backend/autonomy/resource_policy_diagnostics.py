from autonomy.resource_policy import ResourcePolicy
from autonomy.resource_observer import ResourceObservation


def missing_required_metadata(
    policy: ResourcePolicy,
    observation: ResourceObservation,
) -> list[str]:
    metadata = observation.data.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    return sorted(
        key
        for key in policy.required_metadata
        if key not in metadata
    )
