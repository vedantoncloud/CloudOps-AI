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

    def get_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> dict[str, Any]:
        """Return a provider-neutral, read-only resource observation."""
        if not resource_type.strip():
            raise ValueError("resource_type cannot be empty")
        if not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        return {
            "provider": self.provider_name,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
        }
