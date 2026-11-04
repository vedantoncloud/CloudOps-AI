"""Validate a CloudOps SQLite backup by loading it in an isolated temporary copy."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from autonomy.action_plan_store import ActionPlanStore
from autonomy.gitops_registry import GitOpsChangeSetRegistry
from autonomy.persistent_audit_trail import PersistentAuditTrail
from autonomy.persistent_audit_health import PersistentAuditHealthChecker


TABLES = {
    "audit": "audit_events",
    "idempotency": "audit_idempotency",
    "action-plans": "action_plans",
    "gitops": "gitops_change_sets",
}

REQUIRED_COLUMNS = {
    "audit": {"sequence", "event_json", "event_hash"},
    "idempotency": {
        "run_id", "event_type", "evidence_json", "status", "claim_token", "claimed_at"
    },
    "action-plans": {"action_id", "tenant_id", "payload", "created_order"},
    "gitops": {"change_id", "payload", "created_order"},
}


def _load_copy(store: str, path: Path) -> int:
    if store == "audit":
        with sqlite3.connect(path) as connection:
            sequences = [
                row[0]
                for row in connection.execute(
                    "SELECT sequence FROM audit_events ORDER BY sequence"
                )
            ]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("Audit backup event sequence is not contiguous from one")
        restored = PersistentAuditTrail(path)
        integrity = restored.get_integrity_diagnostics()
        if not integrity.valid:
            raise ValueError(f"Audit hash chain failed at event {integrity.first_invalid_index}")
        return integrity.event_count
    if store == "idempotency":
        health = PersistentAuditHealthChecker(path).inspect()
        if not health.evidence.get("consistent") or health.evidence.get("malformed_evidence_claims", 0):
            raise ValueError("Audit idempotency backup contains inconsistent claims")
        pending = PersistentAuditHealthChecker(path).list_pending()
        if len(pending) != health.pending_claims:
            raise ValueError("Audit idempotency pending-claim count is inconsistent")
        return health.total_claims
    if store == "action-plans":
        return len(ActionPlanStore(path).load_all())
    return len(GitOpsChangeSetRegistry(database_path=path).list_all())


def verify_backup(store: str, backup: Path) -> dict[str, int | str]:
    """Check SQLite integrity and application-level readability without changing backup."""
    source = backup.resolve(strict=True)
    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=5) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise ValueError("SQLite integrity check failed")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if TABLES[store] not in tables:
            raise ValueError(f"Backup does not contain the expected {store} store")
        columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({TABLES[store]})")
        }
        if not REQUIRED_COLUMNS[store].issubset(columns):
            raise ValueError(f"Backup {store} store schema is incomplete")

    with tempfile.TemporaryDirectory(prefix="cloudops-restore-drill-") as temporary:
        isolated_copy = Path(temporary) / "restore.db"
        shutil.copyfile(source, isolated_copy)
        count = _load_copy(store, isolated_copy)
        gc.collect()
    return {"store": store, "records_loaded": count}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", choices=sorted(TABLES))
    parser.add_argument("backup", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_backup(args.store, args.backup)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f"Backup restore drill failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
