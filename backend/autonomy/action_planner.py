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

    def plan_from_ec2_insight(
        self,
        instance_id: str,
        insight: dict[str, Any],
    ) -> ActionPlan | None:
        """Convert a supported EC2 insight into an action plan.

        Unsupported insights return None rather than inventing
        an infrastructure action.
        """

        insight_type = insight.get("type")
        severity = insight.get("severity")
        message = insight.get("message")
        recommendation = insight.get("recommendation")

        if not message or not recommendation:
            return None

        risk_mapping = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH,
        }

        risk = risk_mapping.get(severity)

        if risk is None:
            return None

        action_mapping = {
            "high_cpu_utilization": "investigate_cpu_capacity",
            "elevated_cpu_utilization": "review_cpu_utilization",
            "instance_not_running": "review_instance_state",
            "instance_status_issue": "investigate_instance_status",
            "system_status_issue": "investigate_system_status",
            "cpu_data_missing": "verify_cloudwatch_cpu_monitoring",
            "network_data_missing": "verify_cloudwatch_network_monitoring",
        }

        action_type = action_mapping.get(insight_type)

        if action_type is None:
            return None

        return self.plan_ec2_action(
            instance_id=instance_id,
            action_type=action_type,
            reason=message,
            risk=risk,
            metadata={
                "insight_type": insight_type,
                "recommendation": recommendation,
            },
        )

    def plan_from_ec2_insights(
        self,
        instance_id: str,
        insights: list[dict[str, Any]],
    ) -> list[ActionPlan]:
        """Convert supported EC2 insights into action plans."""

        plans = []

        for insight in insights:
            plan = self.plan_from_ec2_insight(
                instance_id=instance_id,
                insight=insight,
            )

            if plan is not None:
                plans.append(plan)

        return plans