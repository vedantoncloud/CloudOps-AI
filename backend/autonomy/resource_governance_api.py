"""Read-only API for resource governance inspection."""

from fastapi import APIRouter, HTTPException

from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyEngine

router = APIRouter(prefix="/autonomy/resources", tags=["resource-governance"])


@router.get("/{resource_type}/{resource_id}/governance")
def resource_governance(resource_type: str, resource_id: str):
    """Inspect governance state without performing infrastructure mutations."""
    try:
        engine = ResourceGovernanceEngine(
            policy_engine=ResourcePolicyEngine(ResourcePolicy())
        )
        raise HTTPException(
            status_code=501,
            detail=(
                "Resource governance API requires an application provider "
                "adapter and does not perform provider mutations."
            ),
        )
    except HTTPException:
        raise
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
