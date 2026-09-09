from autonomy.action_models import ActionPlan, ActionStatus
from autonomy.executor import ExecutionResult


class ActionVerifier:
    """Verify an action against the result returned by the executor."""

    def verify(
        self,
        action: ActionPlan,
        execution_result: ExecutionResult,
    ) -> ActionPlan:
        if action.status != ActionStatus.EXECUTING:
            raise ValueError(
                "Action must be executing before verification."
            )

        if execution_result.action_id != action.action_id:
            raise ValueError(
                "Execution result does not match the action being verified."
            )

        if execution_result.status != ActionStatus.EXECUTING:
            raise ValueError(
                "Execution result must represent an executing action."
            )

        if execution_result.successful:
            action.status = ActionStatus.SUCCEEDED
        else:
            action.status = ActionStatus.ROLLBACK_REQUIRED

        return action
