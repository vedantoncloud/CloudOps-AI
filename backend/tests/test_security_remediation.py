from autonomy.action_models import RiskLevel
from autonomy.security_remediation import (
    SecurityFinding,
    SecurityFindingType,
    SecurityRemediationEngine,
)


def finding(
    finding_type: SecurityFindingType,
    severity: RiskLevel = RiskLevel.HIGH,
) -> SecurityFinding:
    return SecurityFinding(
        resource_id="bucket-123",
        resource_type="s3",
        finding_type=finding_type,
        severity=severity,
        description="Security configuration requires remediation.",
    )


def test_public_access_generates_access_remediation():
    result = SecurityRemediationEngine().create_plan(
        finding(SecurityFindingType.PUBLIC_ACCESS)
    )

    assert result.remediation_action == "review_access_controls"
    assert result.requires_approval is True
    assert result.destructive is False


def test_weak_configuration_generates_configuration_remediation():
    result = SecurityRemediationEngine().create_plan(
        finding(SecurityFindingType.WEAK_CONFIGURATION)
    )

    assert result.remediation_action == "review_security_configuration"


def test_missing_encryption_generates_encryption_remediation():
    result = SecurityRemediationEngine().create_plan(
        finding(SecurityFindingType.MISSING_ENCRYPTION)
    )

    assert result.remediation_action == "enable_encryption"


def test_missing_monitoring_generates_monitoring_remediation():
    result = SecurityRemediationEngine().create_plan(
        finding(SecurityFindingType.MISSING_MONITORING)
    )

    assert result.remediation_action == "enable_security_monitoring"


def test_unknown_finding_is_investigated():
    result = SecurityRemediationEngine().create_plan(
        finding(SecurityFindingType.UNKNOWN)
    )

    assert result.remediation_action == "investigate_security_finding"


def test_critical_findings_still_require_approval():
    result = SecurityRemediationEngine().create_plan(
        finding(
            SecurityFindingType.PUBLIC_ACCESS,
            RiskLevel.CRITICAL,
        )
    )

    assert result.severity == RiskLevel.CRITICAL
    assert result.requires_approval is True


def test_security_engine_never_enables_automatic_execution():
    result = SecurityRemediationEngine().create_plan(
        finding(SecurityFindingType.PUBLIC_ACCESS)
    )

    assert result.details["automatic_execution"] is False
    assert result.details["infrastructure_mutation"] is False


def test_finding_context_is_preserved():
    result = SecurityRemediationEngine().create_plan(
        finding(SecurityFindingType.PUBLIC_ACCESS)
    )

    assert result.resource_id == "bucket-123"
    assert result.resource_type == "s3"
    assert result.finding_type == SecurityFindingType.PUBLIC_ACCESS
    assert result.severity == RiskLevel.HIGH


def test_empty_resource_id_is_rejected():
    bad_finding = SecurityFinding(
        resource_id="",
        resource_type="s3",
        finding_type=SecurityFindingType.PUBLIC_ACCESS,
        severity=RiskLevel.HIGH,
        description="Finding",
    )

    try:
        SecurityRemediationEngine().create_plan(bad_finding)
    except ValueError as exc:
        assert str(exc) == "resource_id cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_empty_resource_type_is_rejected():
    bad_finding = SecurityFinding(
        resource_id="bucket-123",
        resource_type="",
        finding_type=SecurityFindingType.PUBLIC_ACCESS,
        severity=RiskLevel.HIGH,
        description="Finding",
    )

    try:
        SecurityRemediationEngine().create_plan(bad_finding)
    except ValueError as exc:
        assert str(exc) == "resource_type cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_multiple_findings_generate_multiple_plans():
    engine = SecurityRemediationEngine()

    plans = engine.create_plans([
        finding(SecurityFindingType.PUBLIC_ACCESS),
        finding(SecurityFindingType.MISSING_ENCRYPTION),
        finding(SecurityFindingType.MISSING_MONITORING),
    ])

    assert len(plans) == 3
    assert [
        plan.remediation_action
        for plan in plans
    ] == [
        "review_access_controls",
        "enable_encryption",
        "enable_security_monitoring",
    ]
