from dataclasses import dataclass, field
from typing import Any

from autonomy.provider import CloudProvider


@dataclass(frozen=True)
class ResourceObservation:
    """Provider-neutral, read-only resource observation."""

    provider: str
    resource_type: str
    resource_id: str
    data: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True

    @property
    def attributes(self) -> dict[str, Any]:
        return dict(self.data)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "read_only": self.read_only,
            **dict(self.data),
        }


class ResourceObserver:
    """Normalize provider resource reads into a stable provider-neutral contract."""

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

        get_resource = getattr(provider, "get_resource", None)
        if not callable(get_resource):
            raise ValueError(
                f"provider '{provider.provider_name}' does not support resource observation"
            )

        raw = get_resource(
            resource_type=resource_type,
            resource_id=resource_id,
        )

        if not isinstance(raw, dict):
            raise ValueError("provider resource observation must be a dictionary")

        observed_provider = str(raw.get("provider") or provider.provider_name)
        observed_type = str(raw.get("resource_type") or resource_type)
        observed_id = str(raw.get("resource_id") or resource_id)

        if observed_provider != provider.provider_name:
            raise ValueError("provider observation returned mismatched provider")
        if observed_type != resource_type:
            raise ValueError("provider observation returned mismatched resource_type")
        if observed_id != resource_id:
            raise ValueError("provider observation returned mismatched resource_id")

        raw_tags = raw.get("tags", {})
        if isinstance(raw_tags, dict):
            tags = dict(raw_tags)
        elif isinstance(raw_tags, list):
            tags = {}
            for tag in raw_tags:
                if isinstance(tag, dict):
                    key = tag.get("Key", tag.get("key"))
                    value = tag.get("Value", tag.get("value"))
                    if key is not None:
                        tags[str(key)] = value
        else:
            tags = {}

        metadata = dict(raw.get("metadata", {}))
        if not isinstance(raw.get("metadata", {}), dict):
            metadata = {}

        reserved = {
            "provider",
            "resource_type",
            "resource_id",
            "read_only",
            "state",
            "health",
            "tags",
            "metadata",
        }

        for key, value in raw.items():
            if key not in reserved:
                metadata[key] = value

        data = {
            "state": raw.get("state", "unknown"),
            "health": raw.get("health", "unknown"),
            "tags": tags,
            "metadata": metadata,
        }

        return ResourceObservation(
            provider=observed_provider,
            resource_type=observed_type,
            resource_id=observed_id,
            data=data,
            read_only=bool(raw.get("read_only", True)),
        )
