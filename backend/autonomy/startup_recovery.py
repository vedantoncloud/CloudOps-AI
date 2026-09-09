from dataclasses import dataclass
from enum import Enum
from typing import Any

from autonomy.action_models import ActionPlan, ActionStatus


class RecoveryDecision(str, Enum):
    NO_ACTION = "no_action"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class StartupRecoveryResult:
    action_id: str
    previous_status: ActionStatus
    decision: RecoveryDecision
    message: str
    details: dict[str, Any]


class StartupRecoveryManager:
    """Safely identify unfinished actions after an application restart.

    Startup recovery never executes infrastructure actions automatically.
    """

    RECOVERY_REQUIRED_STATUSES = frozenset({
        ActionStatus.EXECUTING,
        ActionStatus.VERIFYING,
        ActionStatus.ROLLBACK_REQUIRED,
    })

    def inspect(self, action: ActionPlan) -> StartupRecoveryResult:
        if action.status in self.RECOVERY_REQUIRED_STATUSES:
            return StartupRecoveryResult(
                action_id=action.action_id,
                previous_status=action.status,
                decision=RecoveryDecision.RECOVERY_REQUIRED,
                message=(
                    "Unfinished action detected after startup; "
                    "manual recovery handling is required."
                ),
                details={
                    "action_type": action.action_type,
                    "resource_type": action.target.resource_type,
                    "resource_id": action.target.resource_id,
                    "automatic_execution": False,
                },
            )

        return StartupRecoveryResult(
            action_id=action.action_id,
            previous_status=action.status,
            decision=RecoveryDecision.NO_ACTION,
            message="No startup recovery is required for this action.",
            details={
                "action_type": action.action_type,
                "resource_type": action.target.resource_type,
                "resource_id": action.target.resource_id,
                "automatic_execution": False,
            },
        )

    def inspect_all(
        self,
        actions: list[ActionPlan],
    ) -> list[StartupRecoveryResult]:
        return [self.inspect(action) for action in actions]
