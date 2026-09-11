from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.action_models import RiskLevel
from autonomy.audit import AuditTrail
from autonomy.audit_api import audit_trail
from autonomy.control_loop_api import router as control_loop_router
from autonomy.gitops import (
    GitOpsChange,
    GitOpsChangeSet,
    GitOpsChangeStatus,
    GitOpsEngine,
)
from autonomy.gitops_registry import GitOpsChangeSetRegistry


def make_change_set(action_id: str = "audit-action") -> GitOpsChangeSet:
    change = GitOpsChange(
        resource_type="infrastructure",
        resource_id="resource-1",
        field="desired_capacity",
        current_value=1,
        desired_value=2,
        reason="audit lifecycle test",
    )

    return GitOpsEngine().create_change_set(
        source_action_id=action_id,
        changes=[change],
        requires_approval=True,
    )


def test_register_emits_audit_event():
    audit = AuditTrail()
    registry = GitOpsChangeSetRegistry(audit_trail=audit)

    change_set = make_change_set()
    registry.register(change_set)

    events = audit.get_events("audit-action")

    assert len(events) == 1
    assert events[0].event == "gitops_change_registered"
    assert events[0].old_status == "none"
    assert events[0].new_status == GitOpsChangeStatus.PENDING_APPROVAL.value


def test_full_gitops_lifecycle_is_audited():
    audit = AuditTrail()
    registry = GitOpsChangeSetRegistry(audit_trail=audit)

    change_set = make_change_set()
    registry.register(change_set)

    registry.approve(change_set.change_id, "operator")

    apply_result = registry.apply(
        change_set.change_id,
        dry_run=True,
    )

    assert apply_result.success is True

    verified = registry.verify(
        change_set.change_id,
        observed_values={"infrastructure/resource-1/desired_capacity": 2},
    )

    assert verified is True

    events = audit.get_events("audit-action")
    names = [event.event for event in events]

    assert names == [
        "gitops_change_registered",
        "gitops_change_approved",
        "gitops_change_applied",
        "gitops_change_verified",
    ]


def test_rejection_is_audited():
    audit = AuditTrail()
    registry = GitOpsChangeSetRegistry(audit_trail=audit)

    change_set = make_change_set("reject-action")
    registry.register(change_set)

    registry.reject(
        change_set.change_id,
        "operator",
        "not required",
    )

    events = audit.get_events("reject-action")

    assert events[-1].event == "gitops_change_rejected"
    assert events[-1].new_status == GitOpsChangeStatus.REJECTED.value
    assert events[-1].details["rejected_by"] == "operator"


def test_control_loop_evaluation_is_audited():
    audit_trail.clear()

    app = FastAPI()
    app.include_router(control_loop_router)

    client = TestClient(app)

    response = client.post(
        "/autonomy/control-loop/evaluate",
        json={
            "action_id": "control-audit-action",
            "action_type": "scale_service",
            "resource_type": "service",
            "resource_id": "svc-audit",
            "reason": "capacity optimization",
            "risk": "low",
            "requires_approval": False,
            "field": "desired_capacity",
            "desired_value": 2,
            "current_value": 1,
        },
    )

    assert response.status_code == 200

    events = audit_trail.get_events("control-audit-action")

    assert any(
        event.event in {
            "control_loop_evaluated",
            "control_loop_blocked",
        }
        for event in events
    )

    audit_trail.clear()

