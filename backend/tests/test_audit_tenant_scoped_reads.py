
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy import audit_api


def test_tenant_audit_list_and_export_use_repository_scoped_reads(monkeypatch):
    calls = []

    def scoped_get_events(action_id=None, *, tenant_id=None, tenant_scoped=False):
        calls.append((action_id, tenant_id, tenant_scoped))
        return []

    monkeypatch.setattr(audit_api.audit_trail, "get_events", scoped_get_events)

    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"tenant-token": Principal("alice", "operator", "account-a")},
    )
    app.include_router(audit_api.router)
    client = TestClient(app)
    headers = {"Authorization": "Bearer tenant-token"}

    listed = client.get("/autonomy/audit/events", headers=headers)
    exported = client.get("/autonomy/audit/events/export", headers=headers)

    assert listed.status_code == 200
    assert listed.json() == []
    assert exported.status_code == 200
    assert exported.text == ""
    assert calls == [
        (None, "account-a", True),
        (None, "account-a", True),
    ]
