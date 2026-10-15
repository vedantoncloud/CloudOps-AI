from autonomy.action_models import ActionPlan, ActionStatus


class ApprovalManager:
    """Manage human approval for planned infrastructure actions."""

    def approve(self, action: ActionPlan, approved_by: str | None = None) -> ActionPlan:
        if action.status != ActionStatus.PENDING_APPROVAL:
            raise ValueError(
                "Only actions pending approval can be approved."
            )

        action.status = ActionStatus.APPROVED
        action.decision_by = approved_by
        action.decision_reason = None
        return action

    def reject(self, action: ActionPlan, rejected_by: str, reason: str) -> ActionPlan:
        if action.status != ActionStatus.PENDING_APPROVAL:
            raise ValueError("Only actions pending approval can be rejected.")
        if not isinstance(rejected_by, str) or not rejected_by.strip():
            raise ValueError("A reviewer identity is required to reject an action.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A rejection reason is required.")

        action.status = ActionStatus.REJECTED
        action.decision_by = rejected_by.strip()
        action.decision_reason = reason.strip()
        return action

    def cancel(self, action: ActionPlan) -> ActionPlan:
        if action.status != ActionStatus.PENDING_APPROVAL:
            raise ValueError(
                "Only actions pending approval can be cancelled."
            )

        action.status = ActionStatus.CANCELLED
        return action
