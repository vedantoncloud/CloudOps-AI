"""Read-only preflight contract for the four legacy SQLite stores."""

from __future__ import annotations

import sqlite3

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_trail import PersistentAuditTrail
from autonomy.action_plan_store import ActionPlanStore
from autonomy.gitops_registry import GitOpsChangeSetRegistry
from persistence_preflight import preflight


def _build_stores(tmp_path):
    paths = {
        "audit_events": tmp_path / "audit-events.db",
        "audit_idempotency": tmp_path / "audit-idempotency.db",
        "action_plans": tmp_path / "action-plans.db",
        "gitops_changes": tmp_path / "gitops.db",
    }

    audit = PersistentAuditTrail(paths["audit_events"])
    audit.record(
        action_id="action-1",
        action_type="inspect",
        resource_type="instance",
        resource_id="i-1",
        old_status="running",
        new_status="failed",
        event="inspection_failed",
    )
    audit.close()

    idempotency = PersistentAuditIdempotencyStore(paths["audit_idempotency"])
    claim = idempotency.claim("run-1", "failure", {"result": "failed"})
    assert idempotency.mark_emitted("run-1", "failure", claim.claim_token)
    idempotency.close()

    plans = ActionPlanStore(paths["action_plans"])
    plans.close()
    gitops = GitOpsChangeSetRegistry(database_path=paths["gitops_changes"])
    gitops.close()
    return paths


def test_preflight_validates_all_four_stores_without_modifying_sources(tmp_path):
    paths = _build_stores(tmp_path)
    before = {name: path.read_bytes() for name, path in paths.items()}

    report = preflight(paths)

    assert report["status"] == "ready"
    assert report["read_only"] is True
    assert {item["store"] for item in report["stores"]} == set(paths)
    assert all(item["status"] == "ok" for item in report["stores"])
    counts = {item["store"]: item["records"] for item in report["stores"]}
    assert counts == {
        "audit_events": 1,
        "audit_idempotency": 1,
        "action_plans": 0,
        "gitops_changes": 0,
    }
    assert {name: path.read_bytes() for name, path in paths.items()} == before


def test_preflight_rejects_invalid_audit_chain(tmp_path):
    paths = _build_stores(tmp_path)
    with sqlite3.connect(paths["audit_events"]) as connection:
        connection.execute("UPDATE audit_events SET event_hash = ?", ("0" * 64,))

    report = preflight(paths)

    assert report["status"] == "not_ready"
    audit = next(item for item in report["stores"] if item["store"] == "audit_events")
    assert audit == {
        "store": "audit_events",
        "status": "invalid",
        "reason": "audit_chain_integrity_failed",
        "records": 1,
    }


def test_preflight_rejects_unknown_idempotency_claim_state(tmp_path):
    paths = _build_stores(tmp_path)
    with sqlite3.connect(paths["audit_idempotency"]) as connection:
        connection.execute(
            "UPDATE audit_idempotency SET status = 'unknown' WHERE run_id = 'run-1'"
        )

    report = preflight(paths)

    assert report["status"] == "not_ready"
    store = next(item for item in report["stores"] if item["store"] == "audit_idempotency")
    assert store == {
        "store": "audit_idempotency",
        "status": "invalid",
        "reason": "claim_consistency_failed",
    }


def test_preflight_reports_missing_source_without_creating_it(tmp_path):
    paths = _build_stores(tmp_path)
    paths["gitops_changes"] = tmp_path / "missing-gitops.db"

    report = preflight(paths)

    assert report["status"] == "not_ready"
    gitops = next(item for item in report["stores"] if item["store"] == "gitops_changes")
    assert gitops == {"store": "gitops_changes", "status": "missing"}
    assert not paths["gitops_changes"].exists()
