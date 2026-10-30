import re
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
        """Return bucket inventory with verified ownership tags for tenant filtering."""
        result = self.service.get_s3_buckets()
        if not isinstance(result, dict) or result.get("status") != "healthy":
            return result
        buckets = result.get("buckets")
        if not isinstance(buckets, list):
            return {
                "service": "s3",
                "status": "unhealthy",
                "error": "Malformed S3 bucket inventory",
            }

        enriched = []
        for bucket in buckets:
            if not isinstance(bucket, dict) or not isinstance(bucket.get("name"), str) or not bucket["name"].strip():
                return {
                    "service": "s3",
                    "status": "unhealthy",
                    "error": "Malformed S3 bucket inventory",
                }
            ownership = self.service.get_s3_bucket_tags(bucket["name"])
            tags = ownership.get("tags") if isinstance(ownership, dict) else None
            if (
                not isinstance(ownership, dict)
                or ownership.get("status") != "healthy"
                or not isinstance(tags, dict)
                or any(not isinstance(key, str) or not isinstance(value, str) for key, value in tags.items())
            ):
                return {
                    "service": "s3",
                    "status": "unhealthy",
                    "error": "Unable to verify S3 bucket ownership tags",
                }
            enriched.append({**bucket, "tags": tags})

        return {**result, "buckets": enriched}

    def get_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> dict[str, Any]:
        """Return read-only details while preserving the base provider contract."""
        base = super().get_resource(resource_type, resource_id)

        normalized_type = resource_type.strip().lower()
        normalized_id = resource_id.strip()

        # Preserve generic observations for resource types not yet supported
        # by AWS inventory discovery (for example, service resources).
        if normalized_type not in {"ec2", "s3"}:
            return base

        if normalized_type == "ec2":
            # Preserve the generic observation for IDs that cannot identify an
            # EC2 instance; avoid sending malformed values to AWS.
            if not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", normalized_id):
                return base
            # DescribeInstances with an InstanceIds filter bypasses inventory
            # pagination and avoids scanning an entire account for one record.
            response = self.service.get_ec2_instance(normalized_id)

            if response.get("status") != "healthy":
                return {
                    **base,
                    "status": "unhealthy",
                    "error": response.get(
                        "error",
                        "Unable to retrieve EC2 inventory",
                    ),
                }

            instance = response.get("instance")

            # Keep the original generic response for unknown resources.
            if instance is None:
                return base

            return {
                **base,
                "status": "healthy",
                "attributes": instance,
            }

        response = self.service.get_s3_bucket_details(normalized_id)
        healthy = response.get("status") == "healthy"

        result = {
            **base,
            "status": response.get("status", "unhealthy"),
            "attributes": (
                {
                    "bucket": response.get("bucket"),
                    "region": response.get("region"),
                }
                if healthy
                else {}
            ),
        }

        if not healthy and response.get("error"):
            result["error"] = response["error"]

        return result
