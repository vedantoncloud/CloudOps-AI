from typing import Any

from autonomy.action_models import (
    ActionPlan,
    ActionTarget,
    RiskLevel,
)


class ActionPlanner:
    """Convert infrastructure insights into safe, structured action plans."""

    def plan_ec2_action(
        self,
        instance_id: str,
        action_type: str,
        reason: str,
        risk: RiskLevel,
        metadata: dict[str, Any] | None = None,
        rollback_available: bool = False,
    ) -> ActionPlan:
        target = ActionTarget(
            resource_type="ec2_instance",
            resource_id=instance_id,
            metadata=metadata or {},
        )

        return ActionPlan(
            action_type=action_type,
            target=target,
            reason=reason,
            risk=risk,
            requires_approval=True,
            rollback_available=rollback_available,
        )

    def plan_s3_action(
        self,
        bucket_name: str,
        action_type: str,
        reason: str,
        risk: RiskLevel,
        metadata: dict[str, Any] | None = None,
        rollback_available: bool = False,
    ) -> ActionPlan:
        target = ActionTarget(
            resource_type="s3_bucket",
            resource_id=bucket_name,
            metadata=metadata or {},
        )

        return ActionPlan(
            action_type=action_type,
            target=target,
            reason=reason,
            risk=risk,
            requires_approval=True,
            rollback_available=rollback_available,
        )