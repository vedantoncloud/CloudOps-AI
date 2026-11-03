"""Exercise the four-store importer against the MySQL 8.4 CI service."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_trail import PersistentAuditTrail
from import_legacy_persistence import run_import


MYSQL_URL = os.environ.get("CLOUDOPS_MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(
    not MYSQL_URL, reason="MySQL CI service is not configured"
)


def _sources(directory):
    identity = uuid.uuid4().hex
    paths = {
        "audit_events": directory / "audit.db",
        "audit_idempotency": directory / "idempotency.db",
        "action_plans": directory / "plans.db",
        "gitops": directory / "gitops.db",
    }

    audit = PersistentAuditTrail(paths["audit_events"])
    audit.record(
        action_id=f"mysql-import-{identity}",
        action_type="import_test",
        resource_type="service",
        resource_id="mysql-source",
        old_status="pending",
        new_status="complete",
        event="import_test_completed",
        details={"tenant_id": "tenant-import"},
    )
    audit.close()

    idempotency = PersistentAuditIdempotencyStore(paths["audit_idempotency"])
    claim = idempotency.claim(
        f"mysql-import-{identity}", "completed", {"result": "ok"}
    )
    assert idempotency.mark_emitted(
        claim.run_id, claim.event_type, claim.claim_token
    )
    idempotency.close()

    with sqlite3.connect(paths["action_plans"]) as connection:
        connection.execute(
            "CREATE TABLE action_plans (action_id TEXT PRIMARY KEY, tenant_id TEXT, payload TEXT NOT NULL, created_order INTEGER NOT NULL)"
        )
        payload = json.dumps({
            "action_id": f"plan-{identity}",
            "action_type": "inspect",
            "target": {"resource_type": "instance", "resource_id": "i-import", "metadata": {}},
            "reason": "MySQL importer integration",
            "risk": "low",
            "requires_approval": False,
            "rollback_available": True,
            "status": "pending",
            "decision_by": None,
            "decision_reason": None,
            "created_at": "2026-11-03T12:00:00+00:00",
        }, separators=(",", ":"))
        connection.execute(
            "INSERT INTO action_plans VALUES (?, ?, ?, ?)",
            (f"plan-{identity}", "tenant-import", payload, 4),
        )

    with sqlite3.connect(paths["gitops"]) as connection:
        connection.execute(
            "CREATE TABLE gitops_change_sets (change_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_order INTEGER NOT NULL)"
        )
        payload = json.dumps({
            "change_id": f"change-{identity}",
            "source_action_id": f"plan-{identity}",
            "changes": [],
            "status": "pending",
            "requires_approval": True,
            "approved_by": None,
            "commit_message": "MySQL importer integration",
            "metadata": {"tenant_id": "tenant-import"},
        }, separators=(",", ":"))
        connection.execute(
            "INSERT INTO gitops_change_sets VALUES (?, ?, ?)",
            (f"change-{identity}", payload, 6),
        )
    return paths, identity


def test_atomic_four_store_import_on_mysql(tmp_path, monkeypatch):
    assert MYSQL_URL
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", MYSQL_URL)
    config = Config("backend/alembic.ini")
    config.set_section_option(
        "alembic", "sqlalchemy.url", MYSQL_URL.replace("%", "%%")
    )
    command.upgrade(config, "head")

    engine = create_engine(MYSQL_URL, future=True)
    try:
        # Other MySQL contract tests run first in this job. Give the importer
        # an isolated empty target while retaining the migrated schema.
        with engine.begin() as connection:
            for table in (
                "audit_events", "audit_idempotency", "action_plans",
                "gitops_change_sets", "persistence_import_runs",
            ):
                connection.execute(text(f"DELETE FROM {table}"))
            connection.execute(text(
                "UPDATE audit_chain_state SET last_sequence = 0, last_hash = '' WHERE singleton_id = 1"
            ))
            connection.execute(text(
                "UPDATE action_plan_state SET last_created_order = 0 WHERE singleton_id = 1"
            ))
            connection.execute(text(
                "UPDATE gitops_state SET last_created_order = 0 WHERE singleton_id = 1"
            ))

        paths, identity = _sources(tmp_path)
        dry_run = run_import(paths, MYSQL_URL)
        assert dry_run["status"] == "dry_run"
        assert dry_run["counts"] == {
            "audit_events": 1,
            "audit_idempotency": 1,
            "action_plans": 1,
            "gitops_change_sets": 1,
        }

        imported = run_import(paths, MYSQL_URL, apply=True)
        assert imported["status"] == "imported"
        assert imported["manifest_sha256"] == dry_run["manifest_sha256"]
        assert run_import(paths, MYSQL_URL, apply=True)["status"] == "already_imported"

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM audit_events")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT COUNT(*) FROM audit_idempotency WHERE status = 'emitted'")
            ).scalar_one() == 1
            plan = connection.execute(
                text("SELECT tenant_id, created_order FROM action_plans")
            ).one()
            assert tuple(plan) == ("tenant-import", 4)
            change = connection.execute(
                text("SELECT tenant_id, created_order FROM gitops_change_sets")
            ).one()
            assert tuple(change) == ("tenant-import", 6)
            assert connection.execute(
                text("SELECT manifest_sha256 FROM persistence_import_runs")
            ).scalar_one() == imported["manifest_sha256"]

        audit = PersistentAuditTrail(MYSQL_URL)
        try:
            assert audit.get_integrity_diagnostics().valid
            assert audit.get_integrity_diagnostics().event_count == 1
            event = audit.get_events()[0]
            assert event.action_id == f"mysql-import-{identity}"
        finally:
            audit.close()
    finally:
        engine.dispose()
