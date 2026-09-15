from dataclasses import dataclass
from typing import Any

from autonomy.provider import CloudProvider


@dataclass(frozen=True)
class ResourceObservation:
    """Normalized, provider-neutral observation of a cloud resource."""

    provider: str
    resource_type: str
    resource_id: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "read_only": True,
            "data": dict(self.data),
        }


class ResourceObserver:
    """Collects read-only resource observations through provider adapters."""

    def observe(
        self,
        provider: CloudProvider,
        resource_type: str,
        resource_id: str,
    ) -> ResourceObservation:
        if not resource_type.strip():
            raise ValueError("resource_type cannot be empty")
        if not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        raw = provider.get_resource(
            resource_type=resource_type,
            resource_id=resource_id,
        )

        data = dict(raw) if isinstance(raw, dict) else {}

        return ResourceObservation(
            provider=provider.provider_name,
            resource_type=resource_type,
            resource_id=resource_id,
            data=data,
        )
