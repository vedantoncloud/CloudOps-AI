from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from auth import AccessControlMiddleware, Principal
from autonomy import audit_api
from autonomy.audit import AuditTrail


TOKENS = {
    "reader": Principal("alice", "reader", "tenant-a"),
    "reader-b": Principal("alice", "reader", "tenant-b"),
    "admin": Principal("dana", "admin", "tenant-a"),
}


@pytest.fixture
def clients(monkeypatch):
    trail = AuditTrail()
    for actor_id, action_id, tenant_id in (
        ("alice", "own", "tenant-a"),
        ("alice", "same-actor-other-tenant", "tenant-b"),
        ("alice", "legacy-unattributed", None),
        ("bob", "foreign-actor-event", "tenant-a"),
    ):
        trail.record(
            action_id=action_id,
            action_type="review",
            resource_type="ec2",
            resource_id=f"i-{action_id}",
            old_status="pending",
            new_status="approved",
            event="approved",
            actor_id=actor_id,
            details={"tenant_id": tenant_id} if tenant_id else {},
        )
    monkeypatch.setattr(audit_api, "audit_trail", trail)
    app = FastAPI()
    app.include_router(audit_api.router)
    app.add_middleware(AccessControlMiddleware, mode="token", tokens=TOKENS)
    return {
        "reader": TestClient(app, headers={"Authorization": "Bearer reader"}),
        "reader-b": TestClient(app, headers={"Authorization": "Bearer reader-b"}),
        "admin": TestClient(app, headers={"Authorization": "Bearer admin"}),
    }


@pytest.mark.parametrize("path", ["/autonomy/audit/events", "/autonomy/audit/events/export"])
def test_reader_audit_feed_and_export_are_actor_and_tenant_scoped(clients, path):
    response = clients["reader"].get(path)

    assert response.status_code == 200
    body = response.text
    assert "own" in body
    assert "foreign-actor-event" not in body
    assert "same-actor-other-tenant" not in body
    assert "legacy-unattributed" not in body


@pytest.mark.parametrize("path", ["/autonomy/audit/events", "/autonomy/audit/events/export"])
def test_same_actor_in_another_tenant_only_sees_its_attributed_events(clients, path):
    response = clients["reader-b"].get(path)

    assert response.status_code == 200
    assert "same-actor-other-tenant" in response.text
    assert "own" not in response.text
    assert "legacy-unattributed" not in response.text
    assert "foreign-actor-event" not in response.text


@pytest.mark.parametrize("path", ["/autonomy/audit/events", "/autonomy/audit/events/export"])
def test_reader_cannot_select_another_actor_for_audit_feed_or_export(clients, path):
    response = clients["reader"].get(path, params={"actor_id": "bob"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Audit events are limited to the authenticated actor"


def test_admin_can_list_audit_events_across_actors(clients):
    response = clients["admin"].get("/autonomy/audit/events")

    assert response.status_code == 200
    assert {event["actor_id"] for event in response.json()} == {"alice", "bob"}
