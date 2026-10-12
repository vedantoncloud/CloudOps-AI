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
        """Return read-only details for a supported AWS resource."""
        super().get_resource(resource_type, resource_id)

        normalized_type = resource_type.strip().lower()
        normalized_id = resource_id.strip()

        if normalized_type == "ec2":
            response = self.service.get_ec2_instances()

            if response.get("status") != "healthy":
                return {
                    "provider": "aws",
                    "resource_type": normalized_type,
                    "resource_id": normalized_id,
                    "status": "unhealthy",
                    "error": response.get("error", "Unable to retrieve EC2 inventory"),
                    "read_only": True,
                }

            instance = next(
                (
                    item for item in response.get("instances", [])
                    if item.get("instance_id") == normalized_id
                ),
                None,
            )

            if instance is None:
                return {
                    "provider": "aws",
                    "resource_type": normalized_type,
                    "resource_id": normalized_id,
                    "status": "not_found",
                    "read_only": True,
                }

            return {
                "provider": "aws",
                "resource_type": normalized_type,
                "resource_id": normalized_id,
                "status": "healthy",
                "attributes": instance,
                "read_only": True,
            }

        if normalized_type == "s3":
            response = self.service.get_s3_bucket_details(normalized_id)
            healthy = response.get("status") == "healthy"

            result = {
                "provider": "aws",
                "resource_type": normalized_type,
                "resource_id": normalized_id,
                "status": response.get("status", "unhealthy"),
                "attributes": (
                    {
                        "bucket": response.get("bucket"),
                        "region": response.get("region"),
                    } if healthy else {}
                ),
                "read_only": True,
            }

            if not healthy and response.get("error"):
                result["error"] = response["error"]

            return result

        raise ValueError(f"unsupported AWS resource type: {resource_type}")
