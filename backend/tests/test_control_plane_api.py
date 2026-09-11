from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.audit_api import audit_trail
from autonomy.audit import AuditTrail
from autonomy.control_plane_api import router
from autonomy.gitops import GitOpsChange, GitOpsChangeStatus, GitOpsEngine
from autonomy.gitops_api import registry


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def setup_function():
    registry.clear()
    audit_trail.clear()


def test_summary_returns_operational_status():
    client = make_client()

    response = client.get("/autonomy/control-plane/summary")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "operational"
    assert data["capabilities"]["governed_gitops"] is True
    assert data["capabilities"]["real_infrastructure_mutation"] is False


def test_summary_reports_empty_control_plane():
    client = make_client()

    response = client.get("/autonomy/control-plane/summary")
    data = response.json()

    assert data["gitops"]["total_changes"] == 0
    assert data["gitops"]["pending_approvals"] == 0
    assert data["audit"]["total_events"] == 0


def test_summary_reports_gitops_status_counts():
    engine = GitOpsEngine()

    pending = engine.create_change_set(
        source_action_id="action-pending",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-pending",
                field="instance_type",
                current_value="t3.small",
                desired_value="t3.medium",
            )
        ],
        requires_approval=True,
    )

    approved = engine.create_change_set(
        source_action_id="action-approved",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-approved",
                field="instance_type",
                current_value="t3.small",
                desired_value="t3.medium",
            )
        ],
        requires_approval=True,
    )
    engine.approve(approved, "vedant")

    registry.register(pending)
    registry.register(approved)

    client = make_client()
    data = client.get("/autonomy/control-plane/summary").json()

    assert data["gitops"]["total_changes"] == 2
    assert data["gitops"]["pending_approvals"] == 1
    assert data["gitops"]["status_counts"]["pending_approval"] == 1
    assert data["gitops"]["status_counts"]["approved"] == 1


def test_summary_reports_recent_gitops_changes():
    engine = GitOpsEngine()

    change_set = engine.create_change_set(
        source_action_id="action-recent",
        changes=[
            GitOpsChange(
                resource_type="s3",
                resource_id="bucket-a",
                field="versioning",
                current_value=False,
                desired_value=True,
            )
        ],
        requires_approval=False,
    )

    registry.register(change_set)

    client = make_client()
    data = client.get("/autonomy/control-plane/summary").json()

    assert len(data["gitops"]["recent_changes"]) == 1
    recent = data["gitops"]["recent_changes"][0]

    assert recent["change_id"] == change_set.change_id
    assert recent["source_action_id"] == "action-recent"
    assert recent["status"] == "proposed"
    assert recent["change_count"] == 1


def test_summary_reports_audit_events():
    audit_trail.record(
        action_id="action-audit",
        action_type="scale",
        resource_type="ec2",
        resource_id="i-audit",
        old_status="running",
        new_status="pending_approval",
        event="gitops_proposed",
        details={"reason": "capacity planning"},
    )

    client = make_client()
    data = client.get("/autonomy/control-plane/summary").json()

    assert data["audit"]["total_events"] == 1

    event = data["audit"]["recent_events"][0]
    assert event["action_id"] == "action-audit"
    assert event["event"] == "gitops_proposed"
    assert event["details"]["reason"] == "capacity planning"


def test_summary_is_read_only():
    client = make_client()

    before_gitops = len(registry)
    before_audit = len(audit_trail.get_events())

    response = client.get("/autonomy/control-plane/summary")

    assert response.status_code == 200
    assert len(registry) == before_gitops
    assert len(audit_trail.get_events()) == before_audit


def test_summary_limits_recent_gitops_changes():
    engine = GitOpsEngine()

    for index in range(12):
        change_set = engine.create_change_set(
            source_action_id=f"action-{index}",
            changes=[
                GitOpsChange(
                    resource_type="ec2",
                    resource_id=f"i-{index}",
                    field="desired_count",
                    current_value=1,
                    desired_value=2,
                )
            ],
            requires_approval=False,
        )
        registry.register(change_set)

    client = make_client()
    data = client.get("/autonomy/control-plane/summary").json()

    assert data["gitops"]["total_changes"] == 12
    assert len(data["gitops"]["recent_changes"]) == 10
    assert data["gitops"]["recent_changes"][0]["source_action_id"] == "action-2"
    assert data["gitops"]["recent_changes"][-1]["source_action_id"] == "action-11"


def test_summary_limits_recent_audit_events():
    for index in range(12):
        audit_trail.record(
            action_id=f"action-{index}",
            action_type="test",
            resource_type="ec2",
            resource_id=f"i-{index}",
            old_status="old",
            new_status="new",
            event="test_event",
        )

    client = make_client()
    data = client.get("/autonomy/control-plane/summary").json()

    assert data["audit"]["total_events"] == 12
    assert len(data["audit"]["recent_events"]) == 10
    assert data["audit"]["recent_events"][0]["action_id"] == "action-2"
    assert data["audit"]["recent_events"][-1]["action_id"] == "action-11"
