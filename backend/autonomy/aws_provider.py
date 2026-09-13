from typing import Any

from autonomy.provider import CloudProvider


class AWSProvider(CloudProvider):
    """AWS provider adapter backed by the existing AWSService."""

    def __init__(self, service: Any) -> None:
        self.service = service

    @property
    def provider_name(self) -> str:
        return "aws"

    def get_ec2_instances(
        self,
        state: str | None = None,
        tag_filter: str | None = None,
    ) -> dict[str, Any]:
        return self.service.get_ec2_instances(
            state=state,
            tag_filter=tag_filter,
        )

    def get_ec2_summary(self) -> dict[str, Any]:
        return self.service.get_ec2_summary()

    def get_s3_buckets(self) -> dict[str, Any]:
        return self.service.get_s3_buckets()
