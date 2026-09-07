from autonomy.action_models import ActionPlan, ActionStatus


class ApprovalManager:
    """Manage human approval for planned infrastructure actions."""

    def approve(self, action: ActionPlan) -> ActionPlan:
        if action.status != ActionStatus.PENDING_APPROVAL:
            raise ValueError(
                "Only actions pending approval can be approved."
            )

        action.status = ActionStatus.APPROVED
        return action

    def cancel(self, action: ActionPlan) -> ActionPlan:
        if action.status != ActionStatus.PENDING_APPROVAL:
            raise ValueError(
                "Only actions pending approval can be cancelled."
            )

        action.status = ActionStatus.CANCELLED
        return action