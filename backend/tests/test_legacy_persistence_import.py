from __future__ import annotations

import json
import sqlite3

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_trail import PersistentAuditTrail
from import_legacy_persistence import run_import


def _make_sources(tmp_path):
    paths = {
        "audit_events": tmp_path / "audit-events.db",
        "audit_idempotency": tmp_path / "audit-idempotency.db",
        "action_plans": tmp_path / "action-plans.db",
        "gitops": tmp_path / "gitops.db",
    }

    audit = PersistentAuditTrail(paths["audit_events"])
    audit.record(
        action_id="action-001",
        action_type="scale",
        resource_type="instance",
        resource_id="i-001",
        old_status="running",
        new_status="stopped",
        event="action_completed",
        details={"tenant_id": "tenant-a"},
    )
    audit.close()

    claims = PersistentAuditIdempotencyStore(paths["audit_idempotency"])
    emitted = claims.claim("run-emitted", "failure", {"reason": "timeout"})
    assert claims.mark_emitted("run-emitted", "failure", emitted.claim_token)
    pending = claims.claim("run-pending", "success", {"result": "ready"})
    assert pending.emitted is True
    claims.close()

    with sqlite3.connect(paths["action_plans"]) as connection:
        connection.execute(
            "CREATE TABLE action_plans (action_id TEXT PRIMARY KEY, tenant_id TEXT, payload TEXT NOT NULL, created_order INTEGER NOT NULL)"
        )
        payload = json.dumps({
            "action_id": "plan-001",
            "action_type": "scale",
            "target": {"resource_type": "instance", "resource_id": "i-001", "metadata": {}},
            "reason": "capacity",
            "risk": "low",
            "requires_approval": False,
            "rollback_available": True,
            "status": "pending",
            "decision_by": None,
            "decision_reason": None,
            "created_at": "2026-11-03T10:00:00+00:00",
        }, separators=(",", ":"))
        connection.execute(
            "INSERT INTO action_plans VALUES (?, ?, ?, ?)",
            ("plan-001", "tenant-a", payload, 9),
        )

    with sqlite3.connect(paths["gitops"]) as connection:
        connection.execute(
            "CREATE TABLE gitops_change_sets (change_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_order INTEGER NOT NULL)"
        )
        payload = json.dumps({
            "change_id": "change-001",
            "source_action_id": "plan-001",
            "changes": [],
            "status": "pending",
            "requires_approval": True,
            "approved_by": None,
            "commit_message": "test migration",
            "metadata": {"tenant_id": "tenant-b"},
        }, separators=(",", ":"))
        connection.execute(
            "INSERT INTO gitops_change_sets VALUES (?, ?, ?)",
            ("change-001", payload, 12),
        )
    return paths


def _migrate_target(tmp_path, monkeypatch):
    target = tmp_path / "target.db"
    url = f"sqlite:///{target}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    return url


def test_import_is_dry_run_by_default_and_preserves_all_store_data(tmp_path, monkeypatch):
    paths = _make_sources(tmp_path)
    before = {name: path.read_bytes() for name, path in paths.items()}
    url = _migrate_target(tmp_path, monkeypatch)

    dry_run = run_import(paths, url)
    assert dry_run["status"] == "dry_run"
    assert dry_run["read_only"] is True
    assert dry_run["counts"] == {
        "audit_events": 1,
        "audit_idempotency": 2,
        "action_plans": 1,
        "gitops_change_sets": 1,
    }
    assert {name: path.read_bytes() for name, path in paths.items()} == before

    imported = run_import(paths, url, apply=True)
    assert imported["status"] == "imported"
    assert imported["manifest_sha256"] == dry_run["manifest_sha256"]

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            audit = connection.execute(
                text("SELECT sequence, event_json, event_hash FROM audit_events")
            ).one()
            assert audit.sequence == 1
            assert json.loads(audit.event_json)["action_id"] == "action-001"
            assert audit.event_hash == dry_run["audit_final_hash"]

            claims = connection.execute(
                text("SELECT run_id, status, claim_token FROM audit_idempotency ORDER BY run_id")
            ).all()
            assert [(row.run_id, row.status) for row in claims] == [
                ("run-emitted", "emitted"),
                ("run-pending", "pending"),
            ]
            assert all(row.claim_token for row in claims)

            plan = connection.execute(
                text("SELECT action_id, tenant_id, created_order FROM action_plans")
            ).one()
            assert tuple(plan) == ("plan-001", "tenant-a", 9)

            change = connection.execute(
                text("SELECT change_id, tenant_id, payload, created_order FROM gitops_change_sets")
            ).one()
            assert (change.change_id, change.tenant_id, change.created_order) == (
                "change-001", "tenant-b", 12
            )
            assert json.loads(change.payload)["metadata"]["tenant_id"] == "tenant-b"

            assert tuple(connection.execute(
                text("SELECT last_sequence, last_hash FROM audit_chain_state")
            ).one()) == (1, dry_run["audit_final_hash"])
            assert connection.execute(
                text("SELECT last_created_order FROM action_plan_state")
            ).scalar_one() == 9
            assert connection.execute(
                text("SELECT last_created_order FROM gitops_state")
            ).scalar_one() == 12
            ledger_count = connection.execute(
                text("SELECT COUNT(*) FROM persistence_import_runs")
            ).scalar_one()
            assert ledger_count == 1
    finally:
        engine.dispose()

    retry = run_import(paths, url, apply=True)
    assert retry["status"] == "already_imported"
    assert retry["manifest_sha256"] == imported["manifest_sha256"]


def test_import_refuses_nonempty_target_without_overwriting(tmp_path, monkeypatch):
    paths = _make_sources(tmp_path)
    url = _migrate_target(tmp_path, monkeypatch)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_events (sequence, event_json, event_hash) "
                "VALUES (1, '{}', :hash)"
            ),
            {"hash": "0" * 64},
        )
    engine.dispose()

    try:
        run_import(paths, url, apply=True)
    except ValueError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("non-empty target must be rejected")

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM audit_events")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM action_plans")).scalar_one() == 0
    finally:
        engine.dispose()


def test_import_manifest_changes_when_any_source_record_changes(tmp_path, monkeypatch):
    paths = _make_sources(tmp_path)
    url = _migrate_target(tmp_path, monkeypatch)
    first = run_import(paths, url)
    with sqlite3.connect(paths["action_plans"]) as connection:
        connection.execute(
            "UPDATE action_plans SET tenant_id = 'tenant-changed' WHERE action_id = 'plan-001'"
        )
    second = run_import(paths, url)
    assert first["manifest_sha256"] != second["manifest_sha256"]
