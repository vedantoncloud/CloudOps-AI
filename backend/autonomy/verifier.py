from autonomy.action_models import ActionPlan, ActionStatus


class ActionVerifier:
    """Verify the result of an executed infrastructure action."""

    def verify(
        self,
        action: ActionPlan,
        successful: bool,
    ) -> ActionPlan:
        if action.status != ActionStatus.EXECUTING:
            raise ValueError(
                "Action must be executing before verification."
            )

        if successful:
            action.status = ActionStatus.SUCCEEDED
        else:
            action.status = ActionStatus.ROLLBACK_REQUIRED

        return action