"""Read-only API for resource governance inspection."""

from fastapi import APIRouter, HTTPException

from autonomy.control_loop_api import provider_registry
from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyEngine
from autonomy.resource_governance_serialization import (
    serialize_governance_report,
)

router = APIRouter(
    prefix="/autonomy/resources",
    tags=["resource-governance"],
)


@router.get("/{resource_type}/{resource_id}/governance")
def resource_governance(resource_type: str, resource_id: str):
    """Inspect governance state without performing infrastructure mutations."""
    try:
        provider = provider_registry.get("aws")

        engine = ResourceGovernanceEngine(
            policy_engine=ResourcePolicyEngine(ResourcePolicy())
        )

        result = engine.inspect(
            provider=provider,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        report = engine.report(result)

        return serialize_governance_report(report)

    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
