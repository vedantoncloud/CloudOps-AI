from autonomy.action_models import ActionPlan, ActionStatus, RiskLevel


class PolicyEngine:
    """Evaluate whether an action is allowed to proceed."""

    def evaluate(self, action: ActionPlan) -> ActionPlan:
        if action.risk == RiskLevel.CRITICAL:
            action.requires_approval = True
            action.status = ActionStatus.PENDING_APPROVAL
            return action

        if action.risk == RiskLevel.HIGH:
            action.requires_approval = True
            action.status = ActionStatus.PENDING_APPROVAL
            return action

        if action.risk == RiskLevel.MEDIUM:
            action.requires_approval = True
            action.status = ActionStatus.PENDING_APPROVAL
            return action

        # LOW-risk actions still remain approval-gated for now.
        action.requires_approval = True
        action.status = ActionStatus.PENDING_APPROVAL

        return action