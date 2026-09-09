from dataclasses import dataclass
from typing import Any

from autonomy.action_models import ActionPlan, ActionStatus


@dataclass(frozen=True)
class RollbackResult:
    action_id: str
    status: ActionStatus
    rolled_back: bool
    message: str
    details: dict[str, Any]


class RollbackManager:
    """Safely handle rollback decisions without mutating infrastructure."""

    def rollback(
        self,
        action: ActionPlan,
        *,
        successful: bool = True,
    ) -> RollbackResult:
        if action.status != ActionStatus.ROLLBACK_REQUIRED:
            raise ValueError(
                "Action must require rollback before rollback can start."
            )

        if not action.rollback_available:
            raise ValueError(
                "Rollback is not available for this action."
            )

        if successful:
            action.status = ActionStatus.ROLLED_BACK
            return RollbackResult(
                action_id=action.action_id,
                status=action.status,
                rolled_back=False,
                message="Rollback validated; no infrastructure mutation was performed.",
                details={
                    "action_type": action.action_type,
                    "resource_type": action.target.resource_type,
                    "resource_id": action.target.resource_id,
                },
            )

        action.status = ActionStatus.FAILED
        return RollbackResult(
            action_id=action.action_id,
            status=action.status,
            rolled_back=False,
            message="Rollback validation failed; no infrastructure mutation was performed.",
            details={
                "action_type": action.action_type,
                "resource_type": action.target.resource_type,
                "resource_id": action.target.resource_id,
            },
        )
