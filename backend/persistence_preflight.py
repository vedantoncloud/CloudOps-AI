"""Read-only preflight of legacy SQLite stores before shared-database migration.

Run with: python persistence_preflight.py
The command never writes to its source databases and emits only sanitized counts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any

from autonomy.action_plan_store import ActionPlanStore
from autonomy.gitops_registry import GitOpsChangeSetRegistry
from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_trail import PersistentAuditTrail


DEFAULT_PATHS = {
    "audit_events": "/var/lib/cloudops/audit-events.db",
    "audit_idempotency": "/var/lib/cloudops/audit-idempotency.db",
    "action_plans": "/var/lib/cloudops/action-plans.db",
    "gitops_changes": "/var/lib/cloudops/gitops.db",
}

ENVIRONMENT_KEYS = {
    "audit_events": "CLOUDOPS_AUDIT_EVENTS_DB",
    "audit_idempotency": "CLOUDOPS_AUDIT_IDEMPOTENCY_DB",
    "action_plans": "CLOUDOPS_ACTION_PLANS_DB_PATH",
    "gitops_changes": "CLOUDOPS_GITOPS_DB_PATH",
}

REQUIRED_COLUMNS = {
    "audit_events": {
        "audit_events": {"sequence", "event_json", "event_hash"},
    },
    "audit_idempotency": {
        "audit_idempotency": {
            "run_id", "event_type", "evidence_json", "status", "claim_token", "claimed_at"
        },
    },
    "action_plans": {
        "action_plans": {"action_id", "tenant_id", "payload", "created_order"},
    },
    "gitops_changes": {
        "gitops_change_sets": {"change_id", "payload", "created_order"},
    },
}


def _snapshot_read_only(source_path: Path, destination_path: Path) -> None:
    """Use SQLite's online backup API from a read-only source connection."""
    with sqlite3.connect(
        f"{source_path.as_uri()}?mode=ro", uri=True, timeout=5
    ) as source, sqlite3.connect(destination_path, timeout=5) as destination:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise sqlite3.DatabaseError("snapshot integrity check failed")


def _validate_sqlite_file(store_name: str, path: Path) -> None:
    with sqlite3.connect(
        f"{path.as_uri()}?mode=ro", uri=True, timeout=5
    ) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise sqlite3.DatabaseError("SQLite integrity check failed")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table_name, expected_columns in REQUIRED_COLUMNS[store_name].items():
            if table_name not in tables:
                raise ValueError("required table is missing")
            columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table_name})")
            }
            if not expected_columns.issubset(columns):
                raise ValueError("required columns are missing")


def _inspect_store(store_name: str, source: Path) -> dict[str, Any]:
    if not source.is_file():
        return {"store": store_name, "status": "missing"}

    try:
        resolved = source.resolve(strict=True)
        _validate_sqlite_file(store_name, resolved)

        if store_name == "audit_idempotency":
            health = PersistentAuditHealthChecker(resolved).inspect()
            if (
                not health.evidence.get("consistent")
                or health.evidence.get("malformed_evidence_claims", 0) > 0
            ):
                return {
                    "store": store_name,
                    "status": "invalid",
                    "reason": "claim_consistency_failed",
                }
            pending = PersistentAuditHealthChecker(resolved).list_pending()
            if len(pending) != health.pending_claims:
                return {
                    "store": store_name,
                    "status": "invalid",
                    "reason": "pending_claim_count_mismatch",
                }
            return {
                "store": store_name,
                "status": "ok",
                "records": health.total_claims,
                "pending": health.pending_claims,
                "emitted": health.emitted_claims,
            }

        with tempfile.TemporaryDirectory(prefix="cloudops-persistence-preflight-") as directory:
            isolated_copy = Path(directory) / "store.db"
            _snapshot_read_only(resolved, isolated_copy)

            if store_name == "audit_events":
                store = PersistentAuditTrail(isolated_copy)
                try:
                    integrity = store.get_integrity_diagnostics()
                    if not integrity.valid:
                        return {
                            "store": store_name,
                            "status": "invalid",
                            "reason": "audit_chain_integrity_failed",
                            "records": integrity.event_count,
                        }
                    return {
                        "store": store_name,
                        "status": "ok",
                        "records": integrity.event_count,
                        "hash_chain_valid": True,
                    }
                finally:
                    store.close()

            if store_name == "action_plans":
                store = ActionPlanStore(isolated_copy)
                try:
                    plans = store.load_all()
                    return {
                        "store": store_name,
                        "status": "ok",
                        "records": len(plans),
                        "tenant_attributed": sum(tenant_id is not None for _, tenant_id in plans),
                    }
                finally:
                    store.close()

            registry = GitOpsChangeSetRegistry(database_path=isolated_copy)
            try:
                changes = registry.list_all()
                return {
                    "store": store_name,
                    "status": "ok",
                    "records": len(changes),
                    "tenant_attributed": sum(
                        isinstance(item.metadata.get("tenant_id"), str)
                        for item in changes
                    ),
                }
            finally:
                registry.close()

    except sqlite3.Error:
        return {"store": store_name, "status": "invalid", "reason": "sqlite_integrity_failed"}
    except (OSError, ValueError, TypeError, KeyError):
        return {"store": store_name, "status": "invalid", "reason": "application_validation_failed"}


def preflight(paths: dict[str, str | Path]) -> dict[str, Any]:
    """Inspect all four source stores without changing any source file."""
    stores = [
        _inspect_store(name, Path(paths[name]))
        for name in ("audit_events", "audit_idempotency", "action_plans", "gitops_changes")
    ]
    ready = all(item["status"] == "ok" for item in stores)
    return {
        "status": "ready" if ready else "not_ready",
        "read_only": True,
        "stores": stores,
    }


def configured_paths() -> dict[str, Path]:
    return {
        store: Path(os.getenv(environment_key, DEFAULT_PATHS[store]))
        for store, environment_key in ENVIRONMENT_KEYS.items()
    }


def main() -> int:
    if os.getenv("CLOUDOPS_DATABASE_URL"):
        print(
            json.dumps(
                {
                    "status": "not_ready",
                    "read_only": True,
                    "reason": "shared_database_already_configured",
                },
                sort_keys=True,
            )
        )
        return 2

    report = preflight(configured_paths())
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
