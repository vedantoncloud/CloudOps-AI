"""Read-only resource inventory discovery through provider adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from autonomy.provider import CloudProvider
from autonomy.provider_registry import ProviderRegistry


@dataclass(frozen=True)
class DiscoveredResource:
    provider: str
    resource_type: str
    resource_id: str
    attributes: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True


class ResourceDiscovery:
    """Discover provider resources without performing infrastructure mutations."""

    SUPPORTED_RESOURCE_TYPES = frozenset({"ec2", "s3"})

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or ProviderRegistry()

    def list_resources(
        self,
        provider: str,
        resource_type: str,
    ) -> list[DiscoveredResource]:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider cannot be empty")
        if not isinstance(resource_type, str) or not resource_type.strip():
            raise ValueError("resource_type cannot be empty")

        normalized_provider = provider.strip().lower()
        normalized_type = resource_type.strip().lower()

        if normalized_type not in self.SUPPORTED_RESOURCE_TYPES:
            raise ValueError(f"unsupported resource type: {resource_type}")

        cloud_provider: CloudProvider = self.registry.get(normalized_provider)

        if normalized_type == "ec2":
            raw = cloud_provider.get_ec2_instances()
            items = self._extract_items(
                raw,
                ("resources", "instances", "Instances"),
            )

            reservations = (
                raw.get("Reservations")
                if isinstance(raw, dict)
                else None
            )

            if isinstance(reservations, list):
                items = []

                for reservation in reservations:
                    if not isinstance(reservation, dict):
                        continue

                    instances = reservation.get("Instances")

                    if isinstance(instances, list):
                        items.extend(
                            instance
                            for instance in instances
                            if isinstance(instance, dict)
                        )
        else:
            raw = cloud_provider.get_s3_buckets()
            items = self._extract_items(
                raw,
                ("resources", "buckets", "Buckets"),
            )

        result: list[DiscoveredResource] = []
        for item in items:
            if not isinstance(item, dict):
                if normalized_type == "s3":
                    continue
                item = {"name": item}

            resource_id = self._resource_id(item, normalized_type)
            if not resource_id:
                continue

            result.append(
                DiscoveredResource(
                    provider=normalized_provider,
                    resource_type=normalized_type,
                    resource_id=resource_id,
                    attributes=deepcopy(item),
                    read_only=True,
                )
            )

        return result

    @staticmethod
    def _extract_items(raw: Any, keys: tuple[str, ...]) -> list[Any]:
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for key in keys:
                value = raw.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    if not value:
                        return []
                    if all(isinstance(v, dict) for v in value.values()):
                        return list(value.values())
                    return []

            if raw and all(isinstance(v, dict) for v in raw.values()):
                return list(raw.values())

            identifier_keys = {
                "resource_id",
                "id",
                "instance_id",
                "InstanceId",
                "bucket_name",
                "name",
                "Name",
            }

            if identifier_keys.intersection(raw):
                return [raw]

        return []

    @staticmethod
    def _resource_id(item: dict[str, Any], resource_type: str) -> str:
        keys = (
            ("resource_id", "id", "instance_id", "InstanceId")
            if resource_type == "ec2"
            else ("resource_id", "id", "bucket_name", "name", "Name")
        )
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
