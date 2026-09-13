from abc import ABC, abstractmethod
from typing import Any


class CloudProvider(ABC):
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
