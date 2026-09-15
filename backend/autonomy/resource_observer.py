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
    """Collects and normalizes read-only resource observations."""

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

        source = dict(raw) if isinstance(raw, dict) else {}

        normalized = {
            "state": source.get("state", "unknown"),
            "health": source.get("health", "unknown"),
            "tags": self._normalize_tags(source.get("tags")),
            "metadata": self._normalize_metadata(source),
        }

        return ResourceObservation(
            provider=provider.provider_name,
            resource_type=resource_type,
            resource_id=resource_id,
            data=normalized,
        )

    @staticmethod
    def _normalize_tags(value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            return {
                str(key): str(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            result: dict[str, str] = {}
            for item in value:
                if isinstance(item, dict) and "Key" in item and "Value" in item:
                    result[str(item["Key"])] = str(item["Value"])
            return result

        return {}

    @staticmethod
    def _normalize_metadata(source: dict[str, Any]) -> dict[str, Any]:
        excluded = {
            "provider",
            "resource_type",
            "resource_id",
            "read_only",
            "state",
            "health",
            "tags",
        }
        return {
            key: value
            for key, value in source.items()
            if key not in excluded
        }
