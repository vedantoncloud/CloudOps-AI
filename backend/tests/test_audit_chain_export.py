import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy.audit_api import router
from autonomy.persistent_audit_trail import PersistentAuditTrail


TOKENS = {
    "reader": Principal("reader", "reader", "tenant-a"),
    "admin": Principal("admin", "admin", "tenant-a"),
}


def make_client(monkeypatch, trail):
    import autonomy.audit_api as audit_api

    monkeypatch.setattr(audit_api, "audit_trail", trail)
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, mode="token", tokens=TOKENS)
    app.include_router(router)
    return TestClient(app)


def test_chain_export_includes_verifiable_events_and_empty_state(tmp_path, monkeypatch):
    trail = PersistentAuditTrail(tmp_path / "audit.db")
    trail.record(
        action_id="a-1", action_type="review", resource_type="s3",
        resource_id="bucket-1", old_status="pending", new_status="approved",
        event="approved", details={"safe": True}, actor_id="operator-1",
    )
    trail.record(
        action_id="a-2", action_type="review", resource_type="ec2",
        resource_id="i-1", old_status="pending", new_status="rejected",
        event="rejected",
    )
    client = make_client(monkeypatch, trail)

    response = client.get("/autonomy/audit/chain/export", headers={"Authorization": "Bearer admin"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "cloudops-audit-chain-v1"
    assert payload["algorithm"] == "sha256"
    assert [row["sequence"] for row in payload["events"]] == [1, 2]
    previous_hash = payload["genesis_hash"]
    for row in payload["events"]:
        assert row["previous_hash"] == previous_hash
        canonical = json.dumps(
            row["event"], sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        expected = hashlib.sha256(previous_hash.encode("ascii") + b"\0" + canonical).hexdigest()
        assert row["event_hash"] == expected
        previous_hash = expected
    assert payload["final_hash"] == previous_hash

    empty = PersistentAuditTrail(tmp_path / "empty.db")
    empty_response = make_client(monkeypatch, empty).get(
        "/autonomy/audit/chain/export", headers={"Authorization": "Bearer admin"}
    )
    assert empty_response.status_code == 200
    assert empty_response.json()["events"] == []
    assert empty_response.json()["final_hash"] == ""


def test_chain_export_requires_admin_and_authentication(tmp_path, monkeypatch):
    client = make_client(monkeypatch, PersistentAuditTrail(tmp_path / "audit.db"))

    assert client.get("/autonomy/audit/chain/export").status_code == 401
    assert client.get(
        "/autonomy/audit/chain/export", headers={"Authorization": "Bearer reader"}
    ).status_code == 403


def test_chain_export_fails_closed_on_tampered_stored_hash(tmp_path, monkeypatch):
    trail = PersistentAuditTrail(tmp_path / "audit.db")
    trail.record(
        action_id="a-1", action_type="review", resource_type="s3",
        resource_id="bucket-1", old_status="pending", new_status="approved",
        event="approved",
    )
    with trail._connect() as connection:
        connection.execute("UPDATE audit_events SET event_hash = ?", ("0" * 64,))
    client = make_client(monkeypatch, trail)

    response = client.get(
        "/autonomy/audit/chain/export", headers={"Authorization": "Bearer admin"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Audit chain integrity check failed"}


def test_chain_export_fails_closed_on_malformed_stored_event(tmp_path, monkeypatch):
    trail = PersistentAuditTrail(tmp_path / "audit.db")
    trail.record(
        action_id="a-1", action_type="review", resource_type="s3",
        resource_id="bucket-1", old_status="pending", new_status="approved",
        event="approved",
    )
    with trail._connect() as connection:
        connection.execute("UPDATE audit_events SET event_json = ?", ("{broken",))
    client = make_client(monkeypatch, trail)

    response = client.get(
        "/autonomy/audit/chain/export", headers={"Authorization": "Bearer admin"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Audit chain integrity check failed"}


def test_chain_export_sanitizes_storage_failures(monkeypatch, tmp_path):
    trail = PersistentAuditTrail(tmp_path / "audit.db")

    def fail_export():
        raise RuntimeError("private database path")

    monkeypatch.setattr(trail, "get_verifiable_export", fail_export)
    client = make_client(monkeypatch, trail)

    response = client.get(
        "/autonomy/audit/chain/export", headers={"Authorization": "Bearer admin"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Audit chain export unavailable"}
    assert "private database path" not in response.text


def test_online_backup_restore_preserves_chain_export(tmp_path):
    import sqlite3

    source = PersistentAuditTrail(tmp_path / "source.db")
    source.record(
        action_id="a-1", action_type="review", resource_type="s3",
        resource_id="bucket-1", old_status="pending", new_status="approved",
        event="approved",
    )
    expected = source.get_verifiable_export()
    backup_path = tmp_path / "backup.db"
    with source._connect() as source_connection:
        with sqlite3.connect(backup_path) as backup_connection:
            source_connection.backup(backup_connection)

    restored = PersistentAuditTrail(tmp_path / "restored.db")
    with sqlite3.connect(backup_path) as backup_connection:
        with restored._connect() as restored_connection:
            backup_connection.backup(restored_connection)

    assert restored.get_verifiable_export() == expected
