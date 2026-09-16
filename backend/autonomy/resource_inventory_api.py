from typing import Any

from fastapi import APIRouter, HTTPException, Query

from autonomy.provider import CloudProvider
from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


router = APIRouter(
    prefix="/autonomy/resources",
    tags=["autonomy-resources"],
)

provider_registry = ProviderRegistry()
discovery = ResourceDiscovery(provider_registry)


def register_provider(provider: CloudProvider) -> None:
    """Register a provider for the read-only resource inventory API."""
    provider_registry.register(provider)


@router.get("")
def list_resources(
    provider: str = Query(default="aws"),
    resource_type: str = Query(default="ec2"),
) -> dict[str, Any]:
    """Return discovered infrastructure resources without mutating them."""
    try:
        resources = discovery.list_resources(
            provider=provider,
            resource_type=resource_type,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "provider": provider.lower(),
        "resource_type": resource_type.lower(),
        "read_only": True,
        "count": len(resources),
        "resources": [
            {
                "provider": item.provider,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "attributes": dict(item.attributes),
                "read_only": item.read_only,
            }
            for item in resources
        ],
    }
