from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CostSignal(str, Enum):
    UNDERUTILIZED = "underutilized"
    UNUSED = "unused"
    STORAGE_OPTIMIZATION = "storage_optimization"
    NO_BILLING_DATA = "no_billing_data"


@dataclass(frozen=True)
class CostOpportunity:
    resource_id: str
    resource_type: str
    signal: CostSignal
    estimated_monthly_savings: float | None
    confidence: str
    recommendation: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class CostOptimizer:
    """Identify cost optimization opportunities without inventing billing data."""

    def analyze_ec2(
        self,
        resource_id: str,
        *,
        average_cpu: float | None,
        monthly_cost: float | None = None,
    ) -> CostOpportunity:
        if not resource_id or not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        if average_cpu is None:
            return CostOpportunity(
                resource_id=resource_id,
                resource_type="ec2",
                signal=CostSignal.NO_BILLING_DATA,
                estimated_monthly_savings=None,
                confidence="low",
                recommendation="Collect sufficient utilization and billing data.",
                reason="CPU utilization data is unavailable.",
            )

        if not 0 <= average_cpu <= 100:
            raise ValueError("average_cpu must be between 0 and 100")

        if average_cpu < 10:
            signal = CostSignal.UNDERUTILIZED
            recommendation = "Review instance sizing or scheduling."
            reason = f"Average CPU utilization is only {average_cpu:.1f}%."
        else:
            signal = CostSignal.NO_BILLING_DATA
            recommendation = "No immediate EC2 cost optimization identified."
            reason = f"Average CPU utilization is {average_cpu:.1f}%."

        savings = None
        confidence = "medium"

        if signal == CostSignal.UNDERUTILIZED and monthly_cost is not None:
            if monthly_cost < 0:
                raise ValueError("monthly_cost cannot be negative")
            savings = round(monthly_cost * 0.30, 2)
            confidence = "estimated"

        return CostOpportunity(
            resource_id=resource_id,
            resource_type="ec2",
            signal=signal,
            estimated_monthly_savings=savings,
            confidence=confidence,
            recommendation=recommendation,
            reason=reason,
            details={
                "average_cpu": average_cpu,
                "monthly_cost_provided": monthly_cost is not None,
                "savings_is_estimate": savings is not None,
            },
        )

    def analyze_s3(
        self,
        bucket_name: str,
        *,
        object_count: int | None,
        total_size_bytes: int | None,
    ) -> CostOpportunity:
        if not bucket_name or not bucket_name.strip():
            raise ValueError("bucket_name cannot be empty")

        if object_count is None or total_size_bytes is None:
            return CostOpportunity(
                resource_id=bucket_name,
                resource_type="s3",
                signal=CostSignal.NO_BILLING_DATA,
                estimated_monthly_savings=None,
                confidence="low",
                recommendation="Collect sufficient storage and billing data.",
                reason="S3 storage usage data is incomplete.",
            )

        if object_count < 0:
            raise ValueError("object_count cannot be negative")
        if total_size_bytes < 0:
            raise ValueError("total_size_bytes cannot be negative")

        if object_count == 0:
            return CostOpportunity(
                resource_id=bucket_name,
                resource_type="s3",
                signal=CostSignal.UNUSED,
                estimated_monthly_savings=None,
                confidence="medium",
                recommendation="Review whether the empty bucket is still required.",
                reason="The bucket contains no objects.",
                details={
                    "object_count": 0,
                    "total_size_bytes": total_size_bytes,
                },
            )

        return CostOpportunity(
            resource_id=bucket_name,
            resource_type="s3",
            signal=CostSignal.STORAGE_OPTIMIZATION,
            estimated_monthly_savings=None,
            confidence="low",
            recommendation="Review storage classes and lifecycle policies.",
            reason=(
                f"Bucket contains {object_count} object(s) using "
                f"{total_size_bytes} byte(s)."
            ),
            details={
                "object_count": object_count,
                "total_size_bytes": total_size_bytes,
                "savings_is_estimate": False,
            },
        )
