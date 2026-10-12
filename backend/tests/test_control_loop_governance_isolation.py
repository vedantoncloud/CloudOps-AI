from types import SimpleNamespace

from autonomy.action_models import (
    ActionPlan,
    ActionStatus,
    ActionTarget,
    RiskLevel,
)
from autonomy.audit import AuditTrail
from autonomy.control_loop_governance import ControlLoopGovernanceGate
from autonomy.governance import GovernanceDecision, GovernanceManager
from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyEngine


class FakeProvider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "state": "running",
            "health": "healthy",
            "tags": {"Environment": "test", "Owner": "platform"},
            "metadata": {"instance_type": "t3.medium"},
        }


def make_action(action_id="same-action"):
    return ActionPlan(
        action_id=action_id,
        action_type="investigate_cpu_capacity",
        target=ActionTarget(resource_type="ec2", resource_id="i-test-001"),
        reason="Governance isolation regression test.",
        risk=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ActionStatus.PENDING_APPROVAL,
    )


def test_governance_records_are_isolated_between_manager_instances():
    action_one = make_action()
    action_two = make_action()

    first_manager = GovernanceManager()
    second_manager = GovernanceManager()

    first_manager.submit(action_one)
    first_manager.approve(action_one, decided_by="operator")

    second_record = second_manager.submit(action_two)

    assert first_manager.get_record(action_one.action_id).decision == (
        GovernanceDecision.APPROVED
    )
    assert second_record.decision == GovernanceDecision.PENDING
    assert second_manager.get_record(action_two.action_id) == second_record


def test_governance_decisions_for_distinct_actions_do_not_leak():
    manager = GovernanceManager()
    approved_action = make_action("approved-action")
    pending_action = make_action("pending-action")

    manager.submit(approved_action)
    manager.submit(pending_action)
    manager.approve(approved_action, decided_by="operator")

    assert manager.get_record("approved-action").decision == (
        GovernanceDecision.APPROVED
    )
    assert manager.get_record("pending-action").decision == (
        GovernanceDecision.PENDING
    )
    assert [record.action_id for record in manager.list_pending()] == [
        "pending-action"
    ]


def test_governance_gate_policy_is_isolated_between_instances():
    provider = FakeProvider()

    deny_ec2_gate = ControlLoopGovernanceGate(
        ResourceGovernanceEngine(
            policy_engine=ResourcePolicyEngine(
                ResourcePolicy(allowed_resource_types={"s3"})
            )
        )
    )
    default_gate = ControlLoopGovernanceGate()

    denied = deny_ec2_gate.evaluate(provider, "ec2", "i-test-001")
    allowed = default_gate.evaluate(provider, "ec2", "i-test-001")

    assert denied.blocked is True
    assert denied.allowed is False
    assert allowed.allowed is True
    assert allowed.blocked is False


def test_audit_trail_instances_do_not_share_events():
    first = AuditTrail()
    second = AuditTrail()

    first.record(
        action_id="blocked-action",
        action_type="control_loop_blocked",
        resource_type="ec2",
        resource_id="i-test-001",
        old_status="pending",
        new_status="blocked",
        event="control_loop_blocked",
        details={"blocked": True},
    )

    assert len(first.get_events()) == 1
    assert second.get_events() == []


def test_governance_block_preserves_legacy_control_loop_blocked_audit_event(
    monkeypatch,
):
    import autonomy.control_loop_api as control_loop_api

    audit = AuditTrail()
    monkeypatch.setattr(control_loop_api, "audit_trail", audit)

    action = make_action("legacy-audit-action")
    gate_result = SimpleNamespace(
        decision=SimpleNamespace(value="deny"),
        blocked=True,
        requires_human_review=False,
        evidence={
            "governance_gate": "deny",
            "policy_decision": "deny",
            "resource_id": "i-test-001",
        },
    )

    control_loop_api._audit_gate_result(action, "aws", gate_result)

    events = audit.get_events(action.action_id)

    assert [event.event for event in events] == [
        "control_loop_governance_blocked",
        "control_loop_blocked",
    ]

    legacy_event = events[1]
    assert legacy_event.action_id == action.action_id
    assert legacy_event.action_type == "control_loop_blocked"
    assert legacy_event.old_status == "pending"
    assert legacy_event.new_status == "blocked"
    assert legacy_event.details["blocked"] is True
    assert legacy_event.details["provider"] == "aws"
    assert legacy_event.details["policy_decision"] == "deny"
