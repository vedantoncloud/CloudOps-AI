from abc import ABC, abstractmethod
from typing import Any


class CloudProvider(ABC):
    """Abstract interface for cloud provider adapters."""

    provider_name: str

    @abstractmethod
    def get_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> dict[str, Any]:
        """Read a cloud resource."""
        raise NotImplementedError
