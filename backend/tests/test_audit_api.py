from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.audit import AuditTrail
from autonomy.audit_api import audit_trail, router
from autonomy.gitops import GitOpsChange, GitOpsEngine


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def make_change_set():
    return GitOpsEngine().create_change_set(
        source_action_id="action-audit-1",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-12345678",
                field="desired_state",
                current_value="running",
                desired_value="stopped",
                reason="audit test",
            )
        ],
        requires_approval=True,
    )


def test_audit_trail_records_and_filters_events():
    trail = AuditTrail()

    event = trail.record(
        action_id="action-1",
        action_type="scale",
        resource_type="ec2",
        resource_id="i-123",
        old_status="pending",
        new_status="approved",
        event="approved",
        details={"approved_by": "operator"},
    )

    assert event.action_id == "action-1"
    assert event.new_status == "approved"
    assert trail.get_events("action-1") == [event]
    assert trail.get_events("missing") == []


def test_audit_api_lists_events():
    client = make_client()
    audit_trail.clear()

    audit_trail.record(
        action_id="action-api-1",
        action_type="scale",
        resource_type="ec2",
        resource_id="i-api",
        old_status="pending_approval",
        new_status="approved",
        event="approved",
        details={"approved_by": "operator"},
    )

    response = client.get("/autonomy/audit/events")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["action_id"] == "action-api-1"
    assert data[0]["event"] == "approved"
    assert data[0]["details"]["approved_by"] == "operator"


def test_audit_api_filters_by_action_id():
    client = make_client()
    audit_trail.clear()

    for action_id in ["action-a", "action-b"]:
        audit_trail.record(
            action_id=action_id,
            action_type="scale",
            resource_type="ec2",
            resource_id=action_id,
            old_status="pending",
            new_status="approved",
            event="approved",
        )

    response = client.get(
        "/autonomy/audit/events",
        params={"action_id": "action-b"},
    )

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["action_id"] == "action-b"


def test_gitops_approval_can_be_audited():
    audit_trail.clear()

    change_set = make_change_set()
    GitOpsEngine().approve(change_set, "operator")

    audit_trail.record(
        action_id=change_set.source_action_id,
        action_type="gitops_change",
        resource_type="infrastructure",
        resource_id=change_set.change_id,
        old_status="pending_approval",
        new_status="approved",
        event="gitops_approved",
        details={"approved_by": "operator"},
    )

    events = audit_trail.get_events(change_set.source_action_id)

    assert len(events) == 1
    assert events[0].event == "gitops_approved"
    assert events[0].details["approved_by"] == "operator"


def test_gitops_apply_and_verify_can_be_audited():
    audit_trail.clear()

    change_set = make_change_set()
    engine = GitOpsEngine()
    engine.approve(change_set, "operator")

    apply_result = engine.apply(change_set, dry_run=True)

    audit_trail.record(
        action_id=change_set.source_action_id,
        action_type="gitops_change",
        resource_type="infrastructure",
        resource_id=change_set.change_id,
        old_status="approved",
        new_status=apply_result.status.value,
        event="gitops_applied",
        details={
            "dry_run": apply_result.dry_run,
            "applied_changes": apply_result.applied_changes,
        },
    )

    verified = engine.verify(change_set)

    audit_trail.record(
        action_id=change_set.source_action_id,
        action_type="gitops_change",
        resource_type="infrastructure",
        resource_id=change_set.change_id,
        old_status="applied",
        new_status=change_set.status.value,
        event="gitops_verified",
        details={"verified": verified},
    )

    events = audit_trail.get_events(change_set.source_action_id)

    assert [event.event for event in events] == [
        "gitops_applied",
        "gitops_verified",
    ]
    assert events[-1].new_status == "verified"


def test_rejected_gitops_change_can_be_audited():
    audit_trail.clear()

    change_set = make_change_set()
    GitOpsEngine().reject(change_set, "operator", "unsafe change")

    audit_trail.record(
        action_id=change_set.source_action_id,
        action_type="gitops_change",
        resource_type="infrastructure",
        resource_id=change_set.change_id,
        old_status="pending_approval",
        new_status="rejected",
        event="gitops_rejected",
        details={
            "rejected_by": "operator",
            "reason": "unsafe change",
        },
    )

    events = audit_trail.get_events(change_set.source_action_id)

    assert len(events) == 1
    assert events[0].event == "gitops_rejected"
    assert events[0].new_status == "rejected"
