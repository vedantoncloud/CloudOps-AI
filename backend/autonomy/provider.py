from abc import ABC, abstractmethod
from typing import Any


class CloudProvider(ABC):
    """Abstract interface for cloud provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the canonical provider name."""
        raise NotImplementedError

    @abstractmethod
    def get_ec2_instances(
        self,
        state: str | None = None,
        tag_filter: str | None = None,
    ) -> dict[str, Any]:
        """Return EC2 instances through the provider adapter."""
        raise NotImplementedError

    @abstractmethod
    def get_ec2_summary(self) -> dict[str, Any]:
        """Return EC2 summary through the provider adapter."""
        raise NotImplementedError

    @abstractmethod
    def get_s3_buckets(self) -> dict[str, Any]:
        """Return S3 bucket information through the provider adapter."""
        raise NotImplementedError
