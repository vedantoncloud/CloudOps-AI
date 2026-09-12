from typing import Any

from autonomy.provider import CloudProvider
from services.aws_service import AWSService


class AWSProvider(CloudProvider):
    """
    AWS implementation of the provider-independent interface.

    This adapter intentionally delegates to the existing AWSService.
    It does not introduce infrastructure mutation operations.
    """

    def __init__(self, service: AWSService | None = None) -> None:
        self.service = service if service is not None else AWSService()

    @property
    def provider_name(self) -> str:
        return "aws"

    def get_ec2_instances(
        self,
        state: str | None = None,
        tag: str | None = None,
    ) -> Any:
        return self.service.get_ec2_instances(state, tag)

    def get_ec2_summary(self) -> Any:
        return self.service.get_ec2_summary()

    def get_s3_buckets(self) -> Any:
        return self.service.get_s3_buckets()
