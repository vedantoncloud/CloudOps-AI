from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from autonomy.action_models import RiskLevel


class SecurityFindingType(str, Enum):
    PUBLIC_ACCESS = "public_access"
    WEAK_CONFIGURATION = "weak_configuration"
    MISSING_ENCRYPTION = "missing_encryption"
    MISSING_MONITORING = "missing_monitoring"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SecurityFinding:
    resource_id: str
    resource_type: str
    finding_type: SecurityFindingType
    severity: RiskLevel
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RemediationPlan:
    resource_id: str
    resource_type: str
    finding_type: SecurityFindingType
    severity: RiskLevel
    remediation_action: str
    requires_approval: bool
    destructive: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class SecurityRemediationEngine:
    """Convert security findings into safe, approval-gated remediation plans."""

    ACTIONS = {
        SecurityFindingType.PUBLIC_ACCESS: "review_access_controls",
        SecurityFindingType.WEAK_CONFIGURATION: "review_security_configuration",
        SecurityFindingType.MISSING_ENCRYPTION: "enable_encryption",
        SecurityFindingType.MISSING_MONITORING: "enable_security_monitoring",
        SecurityFindingType.UNKNOWN: "investigate_security_finding",
    }

    def create_plan(self, finding: SecurityFinding) -> RemediationPlan:
        if not finding.resource_id or not finding.resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        if not finding.resource_type or not finding.resource_type.strip():
            raise ValueError("resource_type cannot be empty")

        action = self.ACTIONS[finding.finding_type]

        return RemediationPlan(
            resource_id=finding.resource_id,
            resource_type=finding.resource_type,
            finding_type=finding.finding_type,
            severity=finding.severity,
            remediation_action=action,
            requires_approval=True,
            destructive=False,
            reason=finding.description,
            details={
                "automatic_execution": False,
                "infrastructure_mutation": False,
            },
        )

    def create_plans(
        self,
        findings: list[SecurityFinding],
    ) -> list[RemediationPlan]:
        return [self.create_plan(finding) for finding in findings]
