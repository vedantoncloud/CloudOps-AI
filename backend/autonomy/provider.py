from abc import ABC, abstractmethod
from typing import Any


class CloudProvider(ABC):
    """Provider-neutral read-only cloud interface for the control plane."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_ec2_instances(
        self,
        state: str | None = None,
        tag_filter: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_ec2_summary(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_s3_buckets(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_capabilities(self) -> list[str]:
        """Return the read-only capabilities exposed by this provider adapter."""
        capability_methods = {
            "compute.instances.list": "get_ec2_instances",
            "compute.instances.summary": "get_ec2_summary",
            "storage.buckets.list": "get_s3_buckets",
            "resources.get": "get_resource",
        }

        return sorted(
            capability
            for capability, method_name in capability_methods.items()
            if callable(getattr(self, method_name, None))
        )

    def get_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> dict[str, Any]:
        """Return a provider-neutral, read-only resource observation."""
        if not isinstance(resource_type, str) or not resource_type.strip():
            raise ValueError("resource_type must be a non-empty string")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValueError("resource_id must be a non-empty string")

        return {
            "provider": self.provider_name,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
        }
