from typing import Any

from autonomy.provider import CloudProvider
from services.aws_service import AWSService


class AWSProvider(CloudProvider):
    """AWS provider adapter backed by the existing AWSService."""

    def __init__(self, service: Any = None) -> None:
        self.service = service if service is not None else AWSService()

    @property
    def provider_name(self) -> str:
        return "aws"

    def get_ec2_instances(
        self,
        state: str | None = None,
        tag_filter: str | None = None,
    ) -> dict[str, Any]:
        return self.service.get_ec2_instances(state, tag_filter)

    def get_ec2_summary(self) -> dict[str, Any]:
        return self.service.get_ec2_summary()

    def get_s3_buckets(self) -> dict[str, Any]:
        return self.service.get_s3_buckets()

    def get_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> dict[str, Any]:
        """Read-only compatibility surface for the provider foundation."""
        return {
            "provider": self.provider_name,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
        }
