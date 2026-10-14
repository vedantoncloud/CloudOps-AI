from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from autonomy.provider import CloudProvider
from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_discovery import ResourceDiscovery


router = APIRouter(
    prefix="/autonomy/resources",
    tags=["autonomy-resources"],
)

provider_registry = ProviderRegistry()
discovery = ResourceDiscovery(provider_registry)
TENANT_TAG = "CloudOpsTenantId"


def _resource_tenant(attributes: dict[str, Any]) -> str | None:
    tags = attributes.get("tags", attributes.get("Tags", {}))
    if isinstance(tags, dict):
        value = tags.get(TENANT_TAG)
        return str(value) if value is not None else None
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get("Key", tag.get("key")) == TENANT_TAG:
                value = tag.get("Value", tag.get("value"))
                return str(value) if value is not None else None
    return None


def register_provider(provider: CloudProvider) -> None:
    """Register a provider for the read-only resource inventory API."""
    provider_registry.register(provider)


@router.get("")
def list_resources(
    request: Request,
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

    tenant_id = getattr(request.state, "tenant_id", None)
    tenant_scoped = getattr(request.state, "tenant_scoped", False)
    if tenant_scoped:
        resources = [
            item for item in resources
            if _resource_tenant(item.attributes) == tenant_id
        ]

    return {
        "provider": provider.strip().lower(),
        "resource_type": resource_type.strip().lower(),
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

