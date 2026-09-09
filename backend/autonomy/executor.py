from dataclasses import dataclass
from typing import Any

from autonomy.action_models import ActionPlan, ActionStatus


@dataclass(frozen=True)
class ExecutionResult:
    action_id: str
    status: ActionStatus
    dry_run: bool
    executed: bool
    message: str
    details: dict[str, Any]


class ActionExecutor:
    """Execute only approved, explicitly allowlisted actions.

    Real AWS mutations remain disabled. Dry-run is the only supported
    execution mode until individual AWS actions have dedicated safety
    implementations and tests.
    """

    ALLOWED_ACTIONS = frozenset(
        {
            "investigate_cpu_capacity",
            "review_cpu_utilization",
            "review_instance_state",
            "investigate_instance_status",
            "investigate_system_status",
            "verify_cloudwatch_cpu_monitoring",
            "verify_cloudwatch_network_monitoring",
            "review_bucket_usage",
            "review_large_object",
            "review_object_lifecycle",
            "review_small_object_optimization",
        }
    )

    def execute(
        self,
        action: ActionPlan,
        *,
        dry_run: bool = True,
    ) -> ExecutionResult:
        if action.status != ActionStatus.APPROVED:
            raise PermissionError(
                "Action must be approved before execution."
            )

        if action.action_type not in self.ALLOWED_ACTIONS:
            raise ValueError(
                f"Action type is not allowlisted: {action.action_type}"
            )

        if not dry_run:
            raise NotImplementedError(
                "Real infrastructure execution is disabled; use dry_run=True."
            )

        action.status = ActionStatus.EXECUTING

        return ExecutionResult(
            action_id=action.action_id,
            status=action.status,
            dry_run=True,
            executed=False,
            message="Dry-run validated; no infrastructure mutation was performed.",
            details={
                "action_type": action.action_type,
                "resource_type": action.target.resource_type,
                "resource_id": action.target.resource_id,
            },
        )
