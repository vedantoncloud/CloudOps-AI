from typing import Any

from autonomy.provider import CloudProvider


class AWSProvider(CloudProvider):
    """Read-only AWS provider adapter foundation."""

    provider_name = "aws"

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def get_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> dict[str, Any]:
        if not resource_type.strip():
            raise ValueError("resource_type cannot be empty")

        if not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        # Provider adapter foundation is intentionally read-only.
        # Actual AWS resource reads can be added behind this interface.
        return {
            "provider": self.provider_name,
            "resource_type": resource_type,
            "resource_id": resource_id,
        }
