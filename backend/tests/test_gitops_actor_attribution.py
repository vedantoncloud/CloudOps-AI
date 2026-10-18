from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy.audit import AuditTrail
from autonomy.gitops import GitOpsChange, GitOpsEngine
from autonomy.gitops_api import registry, router


def make_change_set():
    return GitOpsEngine().create_change_set(
        source_action_id="actor-action",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-actor-123",
                field="instance_type",
                current_value="t3.small",
                desired_value="t3.large",
                reason="Improve capacity",
            )
        ],
    )


def make_client():
    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"tenant-a": Principal("operator-a", "operator", "tenant-a")},
    )
    app.include_router(router)
    return TestClient(app)


def test_gitops_lifecycle_audit_events_attribute_authenticated_actor(monkeypatch):
    trail = AuditTrail()
    monkeypatch.setattr(registry, "audit_trail", trail)
    registry.clear()
    change = make_change_set()
    change.metadata["tenant_id"] = "tenant-a"
    registry.register(change, actor_id="operator-a")
    client = make_client()
    headers = {"Authorization": "Bearer tenant-a"}
    path = f"/autonomy/gitops/changes/{change.change_id}"

    assert client.post(
        f"{path}/approve", headers=headers, json={"approved_by": "forged"}
    ).status_code == 200
    assert client.post(
        f"{path}/apply", headers=headers, json={"dry_run": True}
    ).status_code == 200
    assert client.post(f"{path}/verify", headers=headers, json={}).status_code == 200

    events = trail.get_events("actor-action")
    assert [event.event for event in events] == [
        "gitops_change_registered",
        "gitops_change_approved",
        "gitops_change_applied",
        "gitops_change_verified",
    ]
    assert [event.actor_id for event in events] == ["operator-a"] * 4
    assert change.approved_by == "operator-a"


def test_gitops_rejection_attributes_actor_and_foreign_attempt_is_not_audited(monkeypatch):
    trail = AuditTrail()
    monkeypatch.setattr(registry, "audit_trail", trail)
    registry.clear()
    change = make_change_set()
    change.metadata["tenant_id"] = "tenant-b"
    registry.register(change)
    client = make_client()
    headers = {"Authorization": "Bearer tenant-a"}

    denied = client.post(
        f"/autonomy/gitops/changes/{change.change_id}/reject",
        headers=headers,
        json={"rejected_by": "forged", "reason": "no access"},
    )
    assert denied.status_code == 404
    assert change.status.value == "pending_approval"
    assert len(trail.get_events("actor-action")) == 1

    change.metadata["tenant_id"] = "tenant-a"
    rejected = client.post(
        f"/autonomy/gitops/changes/{change.change_id}/reject",
        headers=headers,
        json={"rejected_by": "forged", "reason": "Risk too high"},
    )
    assert rejected.status_code == 200
    event = trail.get_events("actor-action")[-1]
    assert event.event == "gitops_change_rejected"
    assert event.actor_id == "operator-a"
