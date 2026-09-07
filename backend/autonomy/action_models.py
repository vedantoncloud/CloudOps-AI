from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionStatus(str, Enum):
    PLANNED = "planned"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLBACK_REQUIRED = "rollback_required"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


@dataclass
class ActionTarget:
    resource_type: str
    resource_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.resource_type or not self.resource_type.strip():
            raise ValueError("resource_type cannot be empty")

        if not self.resource_id or not self.resource_id.strip():
            raise ValueError("resource_id cannot be empty")


@dataclass
class ActionPlan:
    action_type: str
    target: ActionTarget
    reason: str
    risk: RiskLevel
    requires_approval: bool = True
    rollback_available: bool = False
    status: ActionStatus = ActionStatus.PLANNED
    action_id: str = field(
        default_factory=lambda: f"act-{uuid4().hex}"
    )

    def __post_init__(self):
        if not self.action_id or not self.action_id.strip():
            raise ValueError("action_id cannot be empty")

        if not self.action_type or not self.action_type.strip():
            raise ValueError("action_type cannot be empty")

        if not self.reason or not self.reason.strip():
            raise ValueError("reason cannot be empty")

        if self.risk == RiskLevel.CRITICAL and not self.requires_approval:
            raise ValueError(
                "critical actions must require approval"
            )