import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy import audit_api
from autonomy.persistent_audit_trail import PersistentAuditTrail


def make_client(role="admin"):
    app = FastAPI()
    app.include_router(audit_api.router)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"test-token": Principal("operator-1", role, "tenant-1")},
    )
    return TestClient(app)


def test_admin_downloads_consistent_audit_database_backup(tmp_path, monkeypatch):
    source = tmp_path / "audit-source.db"
    trail = PersistentAuditTrail(source)
    trail.record(
        action_id="action-1", action_type="inspect", resource_type="instance",
        resource_id="i-1", old_status="running", new_status="running",
        event="inspection_completed", actor_id="operator-1",
    )
    monkeypatch.setattr(audit_api, "audit_trail", trail)
    source_before = source.read_bytes()

    response = make_client().get(
        "/autonomy/audit/database/backup", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.sqlite3"
    assert response.headers["content-disposition"].endswith('.db"')
    backup = tmp_path / "download.db"
    backup.write_bytes(response.content)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        row = connection.execute("SELECT event_json FROM audit_events").fetchone()
        assert '"action_id":"action-1"' in row[0]
    assert source.read_bytes() == source_before


def test_audit_database_backup_requires_admin(tmp_path, monkeypatch):
    trail = PersistentAuditTrail(tmp_path / "audit.db")
    monkeypatch.setattr(audit_api, "audit_trail", trail)

    response = make_client("reader").get(
        "/autonomy/audit/database/backup", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 403


def test_audit_database_backup_maps_unavailable_store_to_sanitized_503(monkeypatch, tmp_path):
    trail = PersistentAuditTrail(tmp_path / "audit.db")
    monkeypatch.setattr(audit_api, "audit_trail", trail)
    trail.database_path = str(tmp_path / "missing" / "private.db")

    response = make_client().get(
        "/autonomy/audit/database/backup", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Audit database backup unavailable"}
    assert "private.db" not in response.text
