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





def test_large_sqlite_backup_streams_beyond_normal_response_limit(tmp_path, monkeypatch):
    from request_limits import ResponseSizeLimitMiddleware

    source = tmp_path / "large-audit.db"
    trail = PersistentAuditTrail(source)
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE backup_payload (payload BLOB)")
        connection.execute(
            "INSERT INTO backup_payload VALUES (?)",
            (b"x" * (5 * 1024 * 1024),),
        )
    monkeypatch.setattr(audit_api, "audit_trail", trail)

    app = FastAPI()
    app.include_router(audit_api.router)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"test-token": Principal("operator-1", "admin", "tenant-1")},
    )
    app.add_middleware(ResponseSizeLimitMiddleware, max_bytes=1024)

    response = TestClient(app).get(
        "/autonomy/audit/database/backup",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert len(response.content) > 5 * 1024 * 1024
    backup = tmp_path / "large-backup.db"
    backup.write_bytes(response.content)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        payload = connection.execute(
            "SELECT length(payload) FROM backup_payload"
        ).fetchone()
    assert payload == (5 * 1024 * 1024,)


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


def test_action_plan_database_backup_is_admin_only_and_integrity_checked(monkeypatch, tmp_path):
    from autonomy import api

    source = tmp_path / "plans.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE action_plans (action_id TEXT)")
        connection.execute("INSERT INTO action_plans VALUES ('plan-1')")
    monkeypatch.setattr(api, "action_plan_store", type("Store", (), {"database_path": source})())

    denied = make_client("reader").get(
        "/autonomy/audit/database/backup/action-plans", headers={"Authorization": "Bearer test-token"}
    )
    assert denied.status_code == 403

    response = make_client().get(
        "/autonomy/audit/database/backup/action-plans", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    backup = tmp_path / "plans-backup.db"
    backup.write_bytes(response.content)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT action_id FROM action_plans").fetchone() == ("plan-1",)


def test_gitops_database_backup_maps_unavailable_store_to_sanitized_503(monkeypatch):
    from autonomy import gitops_api

    monkeypatch.setattr(gitops_api, "registry", type("Registry", (), {"database_path": "/missing/private.db"})())
    response = make_client().get(
        "/autonomy/audit/database/backup/gitops", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "GitOps database backup unavailable"}
    assert "private.db" not in response.text


def test_gitops_database_backup_preserves_store_data(monkeypatch, tmp_path):
    from autonomy import gitops_api

    source = tmp_path / "gitops.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE gitops_change_sets (change_id TEXT)")
        connection.execute("INSERT INTO gitops_change_sets VALUES ('change-1')")
    monkeypatch.setattr(gitops_api, "registry", type("Registry", (), {"database_path": source})())
    before = source.read_bytes()

    response = make_client().get(
        "/autonomy/audit/database/backup/gitops", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    backup = tmp_path / "gitops-backup.db"
    backup.write_bytes(response.content)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT change_id FROM gitops_change_sets").fetchone() == ("change-1",)
    assert source.read_bytes() == before


def test_unknown_database_backup_store_is_rejected():
    response = make_client().get(
        "/autonomy/audit/database/backup/other", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 404
