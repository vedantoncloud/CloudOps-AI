from autonomy.action_models import ActionPlan, ActionStatus


class ActionExecutor:
    """Execute approved infrastructure actions.

    Real AWS mutations will be added only after the approval
    boundary and execution safety checks are fully tested.
    """

    def execute(self, action: ActionPlan) -> ActionPlan:
        if action.status != ActionStatus.APPROVED:
            raise PermissionError(
                "Action must be approved before execution."
            )

        action.status = ActionStatus.EXECUTING

        # Real infrastructure execution will be implemented here.
        # For now, execution is intentionally not connected to AWS.

        raise NotImplementedError(
            "Infrastructure execution is not implemented yet."
        )