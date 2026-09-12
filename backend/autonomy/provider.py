from abc import ABC, abstractmethod
from typing import Any


class CloudProvider(ABC):
    """Provider-independent read-only cloud interface."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier."""
        raise NotImplementedError

    @abstractmethod
    def get_ec2_instances(
        self,
        state: str | None = None,
        tag: str | None = None,
    ) -> Any:
        """Return EC2 instances."""
        raise NotImplementedError

    @abstractmethod
    def get_ec2_summary(self) -> Any:
        """Return an EC2 summary."""
        raise NotImplementedError

    @abstractmethod
    def get_s3_buckets(self) -> Any:
        """Return S3 buckets."""
        raise NotImplementedError
